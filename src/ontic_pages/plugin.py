"""The ontic-pages plugin for Claude Code, installed and kept current on every run.

The plugin (`claude-plugin/` in this repository, listed by `.claude-plugin/marketplace.json`)
shows the last page published in a Claude Code session as a link above the prompt, and adds a
`/page` command that prints it. It is not package data: Claude Code installs it from the
repository on GitHub.

Wherever the skill is synced, `sync_plugin` runs too. When the Claude Code folder exists and
`claude` is on PATH, it reads Claude Code's record of installed plugins
(`plugins/installed_plugins.json`, the user-scope entry); when ours is missing it starts
`claude plugin install`, when it is older than VERSION a marketplace refresh then
`claude plugin update --scope user`. Those run in a detached worker, each step under a time
limit (its process group killed past it), so no command waits on them. Each Claude Code folder
and version is tried at most once a day: the attempts are kept in `plugin-sync.json` in the
ontic-pages config folder, checked and recorded under a lock so two commands at once start one
worker; the steps' output goes to `plugin-sync.log` beside it. The plugin takes effect in Claude
Code sessions started after the install. When current it costs a stat and a small read; it
prints nothing and never raises. `ONTIC_AGENT_SKILLS=0` turns it off, as for the skill; on
systems without `fcntl` (native Windows) it is off.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path

from . import config, skills

try:
    import fcntl  # the lock and the worker's fork are Unix only; elsewhere the sync is off
except ImportError:
    fcntl = None

NAME = "ontic-pages"
MARKETPLACE = "ontic-pages"
SOURCE = "onticlabs/ontic-pages"
# The version in claude-plugin/.claude-plugin/plugin.json. tests/test_plugin.py pins both to a
# hash of the plugin's files: bump them together whenever the plugin changes, so installed
# copies are updated.
VERSION = "0.1.0"
RETRY_SECONDS = 24 * 3600
STEP_SECONDS = 300

# The detached worker: forks so the command that started it can reap it at once, then runs the
# steps (a JSON list of argv lists) one after another, each in its own process group, stopping
# at the first that fails or outlasts STEP_SECONDS.
WORKER = """
import json, os, signal, subprocess, sys
if os.fork():
    os._exit(0)
os.setsid()
for step in json.loads(sys.argv[1]):
    proc = subprocess.Popen(step, stdin=subprocess.DEVNULL, start_new_session=True)
    try:
        code = proc.wait(timeout=float(sys.argv[2]))
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        print(f"timed out: {step}", flush=True)
        sys.exit(1)
    if code:
        sys.exit(code)
"""


def claude_root(env: Mapping[str, str]) -> Path:
    return Path(env.get("CLAUDE_CONFIG_DIR") or "~/.claude").expanduser()


def installed_version(root: Path) -> str | None:
    """The version of ours Claude Code has installed at user scope, or None."""
    try:
        record = json.loads((root / "plugins" / "installed_plugins.json").read_text("utf-8"))
        for entry in record["plugins"][f"{NAME}@{MARKETPLACE}"]:
            if entry.get("scope") == "user":
                return str(entry["version"])
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    return None


def older(found: str, wanted: str) -> bool:
    def parts(version: str) -> tuple[int, ...]:
        return tuple(int(p) for p in version.split("."))

    try:
        return parts(found) < parts(wanted)
    except ValueError:
        return True


def commands(claude: str, found: str | None) -> list[list[str]]:
    """What brings the user-scope plugin to VERSION: an install, or a refresh of the marketplace
    then an update."""
    if found is None:
        return [[claude, "plugin", "install", NAME, "--marketplace", SOURCE, "--scope", "user"]]
    return [
        [claude, "plugin", "marketplace", "update", MARKETPLACE],
        [claude, "plugin", "update", f"{NAME}@{MARKETPLACE}", "--scope", "user"],
    ]


def claim_attempt(folder: Path, key: str, now: float) -> bool:
    """Record an attempt for `key` (a Claude Code folder and a version) unless one was made
    within RETRY_SECONDS; True when this caller may go ahead. Checked and written under a lock,
    so of several commands at once only one goes ahead."""
    folder.mkdir(parents=True, exist_ok=True)
    stamp = folder / "plugin-sync.json"
    with open(folder / "plugin-sync.lock", "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False  # another command is deciding right now
        try:
            tried = json.loads(stamp.read_text("utf-8"))
            if not isinstance(tried, dict):
                tried = {}
        except (OSError, ValueError):
            tried = {}
        last = tried.get(key)
        if isinstance(last, int | float) and now - last < RETRY_SECONDS:
            return False
        tried = {k: t for k, t in tried.items() if isinstance(t, int | float)}
        tried[key] = now
        temp = stamp.with_name(f"{stamp.name}.{os.getpid()}.tmp")
        temp.write_text(json.dumps(tried), "utf-8")
        temp.replace(stamp)
        return True


def start_detached(steps: list[list[str]], log: Path) -> None:
    """Hand the steps to a worker that outlives this process; returns once the worker has
    forked away (a few milliseconds)."""
    with open(log, "a", encoding="utf-8") as out:
        proc = subprocess.Popen(
            [sys.executable, "-c", WORKER, json.dumps(steps), str(STEP_SECONDS)],
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
        )
    proc.wait(timeout=10)


def sync_plugin(
    env: Mapping[str, str] | None = None,
    clock: Callable[[], float] = time.time,
    start: Callable[[list[list[str]], Path], None] = start_detached,
) -> None:
    """Install or update the plugin in the background when it is missing or old. Never
    raises."""
    env = os.environ if env is None else env
    if fcntl is None or skills.turned_off(env):
        return
    try:
        root = claude_root(env)
        claude = shutil.which("claude", path=env.get("PATH"))
        if not root.is_dir() or claude is None:
            return
        found = installed_version(root)
        if found is not None and not older(found, VERSION):
            return
        folder = config.config_path().parent
        if claim_attempt(folder, f"{root.resolve()} {VERSION}", clock()):
            start(commands(claude, found), folder / "plugin-sync.log")
    except (OSError, subprocess.SubprocessError, ValueError):
        return  # never in the way of the command that ran it
