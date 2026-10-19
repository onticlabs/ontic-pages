import json
import stat
import time
from pathlib import Path

import pytest

from ontic_pages import plugin

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "claude-plugin" / ".claude-plugin" / "plugin.json"
MARKETPLACE = REPO / ".claude-plugin" / "marketplace.json"
DAY = 24 * 3600


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


def record(home, version):
    plugins = home / ".claude" / "plugins"
    plugins.mkdir(parents=True, exist_ok=True)
    entry = {"scope": "user", "version": version}
    body = {"version": 2, "plugins": {"ontic-pages@ontic-pages": [entry]}}
    (plugins / "installed_plugins.json").write_text(json.dumps(body))


def sync(now=1000.0):
    started = []
    plugin.sync_plugin(clock=lambda: now, start=lambda steps, log: started.append(steps))
    return started


def test_version_matches_the_manifest():
    assert json.loads(MANIFEST.read_text())["version"] == plugin.VERSION


def test_marketplace_lists_the_plugin():
    listed = json.loads(MARKETPLACE.read_text())
    assert listed["name"] == plugin.MARKETPLACE
    (entry,) = listed["plugins"]
    assert entry["name"] == plugin.NAME
    assert (REPO / entry["source"] / ".claude-plugin" / "plugin.json").is_file()


def test_installs_when_missing(home):
    (steps,) = sync()
    assert [step[1:] for step in steps] == [
        ["plugin", "install", "ontic-pages", "--marketplace", "onticlabs/ontic-pages",
         "--scope", "user"],
    ]  # fmt: skip


def test_updates_when_older(home):
    record(home, "0.0.9")
    (steps,) = sync()
    assert [step[1:] for step in steps] == [
        ["plugin", "marketplace", "update", "ontic-pages"],
        ["plugin", "update", "ontic-pages@ontic-pages"],
    ]


@pytest.mark.parametrize("version", [plugin.VERSION, "99.0.0"])
def test_leaves_current_or_newer_alone(home, version):
    record(home, version)
    assert sync() == []


def test_tries_once_a_day(home):
    assert len(sync(now=1000.0)) == 1
    assert sync(now=1000.0 + DAY - 1) == []
    assert len(sync(now=1000.0 + DAY)) == 1


def test_skips_without_claude_or_its_folder(home, monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert sync() == []
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    (home / ".claude").rmdir()
    assert sync() == []


def test_turned_off(home, monkeypatch):
    monkeypatch.setenv("ONTIC_AGENT_SKILLS", "0")
    assert sync() == []


def test_unreadable_record_counts_as_missing(home):
    (home / ".claude" / "plugins").mkdir()
    (home / ".claude" / "plugins" / "installed_plugins.json").write_text("{not json")
    (steps,) = sync()
    assert steps[0][1:3] == ["plugin", "install"]


def test_start_failing_never_raises(home):
    def boom(steps, log):
        raise OSError("no sh")

    plugin.sync_plugin(start=boom)


def test_start_detached_runs_the_steps_in_order(tmp_path):
    out = tmp_path / "out"
    log = tmp_path / "log"
    steps = [["sh", "-c", f"echo one >> {out}"], ["sh", "-c", f"echo 'two words' >> {out}"]]
    plugin.start_detached(steps, log)
    for _ in range(100):
        if out.exists() and out.read_text().count("\n") == 2:
            break
        time.sleep(0.05)
    assert out.read_text() == "one\ntwo words\n"
