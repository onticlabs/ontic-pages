import fcntl
import hashlib
import json
import stat
import time
from pathlib import Path

import pytest

from ontic_pages import plugin

REPO = Path(__file__).resolve().parent.parent
PLUGIN_DIR = REPO / "claude-plugin"
MANIFEST = PLUGIN_DIR / ".claude-plugin" / "plugin.json"
MARKETPLACE = REPO / ".claude-plugin" / "marketplace.json"
DAY = 24 * 3600
# The plugin's files as of plugin.VERSION. When they change, bump the version in plugin.json and
# plugin.VERSION, then this hash, so installed copies are updated.
PLUGIN_SHA256 = "880cd8150b78731825c4c43cb33e75bd1e95f9a54e87ae066e04a2d3b522a721"
PLUGIN_VERSION = "0.1.0"


def plugin_hash() -> str:
    """A hash of the plugin's files, less the types Claude Code lays in its folder and the
    manifest's version line."""
    digest = hashlib.sha256()
    for path in sorted(PLUGIN_DIR.rglob("*")):
        rel = path.relative_to(PLUGIN_DIR).as_posix()
        if not path.is_file() or rel.startswith(".claude-plugin/types/"):
            continue
        text = path.read_text("utf-8")
        if path == MANIFEST:
            text = "\n".join(line for line in text.splitlines() if '"version"' not in line)
        digest.update(f"{rel}\n{text}\n".encode())
    return digest.hexdigest()


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A home with ~/.claude and a `claude` on PATH, the sync turned on."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude = bin_dir / "claude"
    claude.write_text("#!/bin/sh\n")
    claude.chmod(claude.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    for name in ("ONTIC_AGENT_SKILLS", "CLAUDE_CONFIG_DIR"):
        monkeypatch.delenv(name, raising=False)
    return home


def record(home, *entries):
    """Claude Code's record of installed plugins, with ours at these (scope, version)."""
    plugins = home / ".claude" / "plugins"
    plugins.mkdir(parents=True, exist_ok=True)
    ours = [{"scope": scope, "version": version} for scope, version in entries]
    body = {"version": 2, "plugins": {"ontic-pages@ontic-pages": ours}}
    (plugins / "installed_plugins.json").write_text(json.dumps(body))


def sync(now=1000.0):
    started = []
    plugin.sync_plugin(clock=lambda: now, start=lambda steps, log: started.append(steps))
    return started


def test_version_pinned_to_the_plugin_files():
    assert json.loads(MANIFEST.read_text())["version"] == plugin.VERSION == PLUGIN_VERSION
    assert plugin_hash() == PLUGIN_SHA256, "the plugin changed: bump its version and this hash"


def test_marketplace_lists_the_plugin():
    listed = json.loads(MARKETPLACE.read_text())
    assert listed["name"] == plugin.MARKETPLACE
    (entry,) = listed["plugins"]
    assert entry["name"] == plugin.NAME
    assert (REPO / entry["source"]).resolve() == PLUGIN_DIR


def test_installs_when_missing(home):
    (steps,) = sync()
    assert [step[1:] for step in steps] == [
        ["plugin", "install", "ontic-pages", "--marketplace", "onticlabs/ontic-pages",
         "--scope", "user"],
    ]  # fmt: skip


def test_updates_when_older(home):
    record(home, ("user", "0.0.9"))
    (steps,) = sync()
    assert [step[1:] for step in steps] == [
        ["plugin", "marketplace", "update", "ontic-pages"],
        ["plugin", "update", "ontic-pages@ontic-pages", "--scope", "user"],
    ]


@pytest.mark.parametrize("version", [plugin.VERSION, "99.0.0"])
def test_leaves_current_or_newer_alone(home, version):
    record(home, ("user", version))
    assert sync() == []


def test_reads_only_the_user_scope(home):
    record(home, ("project", plugin.VERSION), ("user", "0.0.9"))
    (steps,) = sync()
    assert steps[-1][1:3] == ["plugin", "update"]
    record(home, ("project", plugin.VERSION))
    (steps,) = sync(now=1000.0 + DAY)
    assert steps[0][1:3] == ["plugin", "install"]


def test_tries_once_a_day(home):
    assert len(sync(now=1000.0)) == 1
    assert sync(now=1000.0 + DAY - 1) == []
    assert len(sync(now=1000.0 + DAY)) == 1


def test_each_version_has_its_own_day(home, monkeypatch):
    assert len(sync()) == 1
    monkeypatch.setattr(plugin, "VERSION", "0.2.0")
    assert len(sync()) == 1
    for version in (plugin.VERSION, "0.1.0"):
        monkeypatch.setattr(plugin, "VERSION", version)
        assert sync() == []


def test_another_command_deciding_wins(home, tmp_path):
    folder = tmp_path / "config" / "ontic-pages"
    folder.mkdir(parents=True)
    with open(folder / "plugin-sync.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        assert sync() == []
    assert len(sync()) == 1


def test_skips_without_claude_or_its_folder(home, monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert sync() == []
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    (home / ".claude").rmdir()
    assert sync() == []


def test_turned_off(home, monkeypatch):
    monkeypatch.setenv("ONTIC_AGENT_SKILLS", "0")
    assert sync() == []


@pytest.mark.parametrize("text", ["{not json", "[]", '{"plugins": {"ontic-pages@ontic-pages": 3}}'])
def test_unreadable_record_counts_as_missing(home, text):
    (home / ".claude" / "plugins").mkdir()
    (home / ".claude" / "plugins" / "installed_plugins.json").write_text(text)
    (steps,) = sync()
    assert steps[0][1:3] == ["plugin", "install"]


def test_unreadable_stamp_is_a_fresh_start(home, tmp_path):
    folder = tmp_path / "config" / "ontic-pages"
    folder.mkdir(parents=True)
    (folder / "plugin-sync.json").write_text("[1, 2")
    assert len(sync()) == 1


def test_start_failing_never_raises(home):
    def boom(steps, log):
        raise OSError("no python")

    plugin.sync_plugin(start=boom)


def wait_for(check):
    for _ in range(200):
        if check():
            return
        time.sleep(0.05)
    raise AssertionError("the worker did not get there")


def test_worker_runs_the_steps_in_order(tmp_path):
    out = tmp_path / "out"
    steps = [["sh", "-c", f"echo one >> {out}"], ["sh", "-c", f"echo 'two words' >> {out}"]]
    plugin.start_detached(steps, tmp_path / "log")
    wait_for(lambda: out.exists() and out.read_text().count("\n") == 2)
    assert out.read_text() == "one\ntwo words\n"


def test_worker_stops_at_a_failed_or_slow_step(tmp_path, monkeypatch):
    out = tmp_path / "out"
    log = tmp_path / "log"
    plugin.start_detached([["false"], ["sh", "-c", f"echo ran >> {out}"]], log)
    monkeypatch.setattr(plugin, "STEP_SECONDS", 0.5)
    plugin.start_detached([["sleep", "30"], ["sh", "-c", f"echo ran >> {out}"]], log)
    wait_for(lambda: "timed out" in log.read_text())
    time.sleep(0.3)
    assert not out.exists()
