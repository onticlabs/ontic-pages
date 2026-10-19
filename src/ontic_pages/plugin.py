"""The ontic-pages plugin for Claude Code, installed and kept current on every run.

The plugin (`claude-plugin/` in this repository, listed by `.claude-plugin/marketplace.json`)
shows the last page published in a Claude Code session as a link above the prompt, and adds a
`/page` command that prints it. It is not package data: Claude Code installs it from the
repository on GitHub.

Wherever the skill is synced, `sync_plugin` runs too. When the Claude Code folder exists and
`claude` is on PATH, it reads Claude Code's record of installed plugins
(`plugins/installed_plugins.json`); when ours is missing it starts `claude plugin install`, when
it is older than VERSION a marketplace refresh then `claude plugin update`, in a detached
process, so no command waits on it. It tries at most once a day per version (a stamp in the
ontic-pages config folder, the command's output in a log beside it). The plugin takes effect in
Claude Code sessions started after the install. It costs a stat and a small read when current,
prints nothing and never raises. `ONTIC_AGENT_SKILLS=0` turns it off, as for the skill.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import time
from collections.abc import Callable, Mapping
from pathlib import Path

from . import config, skills

NAME = "ontic-pages"
MARKETPLACE = "ontic-pages"
SOURCE = "onticlabs/ontic-pages"
# The version in claude-plugin/.claude-plugin/plugin.json (tests/test_plugin.py pins it). Bump
# both whenever the plugin changes, so installed copies are updated.
VERSION = "0.1.0"
RETRY_SECONDS = 24 * 3600


def claude_root(env: Mapping[str, str]) -> Path:
    return Path(env.get("CLAUDE_CONFIG_DIR") or "~/.claude").expanduser()


def installed_version(root: Path) -> str | None:
    """The version of ours Claude Code has installed, or None."""
    try:
        record = json.loads((root / "plugins" / "installed_plugins.json").read_text("utf-8"))
        entries = record["plugins"][f"{NAME}@{MARKETPLACE}"]
        return str(entries[0]["version"])
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return None


def older(found: str, wanted: str) -> bool:
    def parts(version: str) -> tuple[int, ...]:
        return tuple(int(p) for p in version.split("."))

    try:
        return parts(found) < parts(wanted)
    except ValueError:
        return True


def commands(claude: str, found: str | None) -> list[list[str]]:
    """What brings the plugin to VERSION: an install, or a refresh of the marketplace then an
    update."""
    if found is None:
        return [[claude, "plugin", "install", NAME, "--marketplace", SOURCE, "--scope", "user"]]
    return [
        [claude, "plugin", "marketplace", "update", MARKETPLACE],
        [claude, "plugin", "update", f"{NAME}@{MARKETPLACE}"],
    ]


def tried_recently(stamp: Path, now: float) -> bool:
    try:
        last = json.loads(stamp.read_text("utf-8"))
        return last["version"] == VERSION and now - float(last["at"]) < RETRY_SECONDS
    except (OSError, ValueError, KeyError, TypeError):
        return False


def start_detached(steps: list[list[str]], log: Path) -> None:
    """Run the steps one after another, each only if the one before succeeded, in a process
    of its own that outlives this one."""
    script = " && ".join(shlex.join(step) for step in steps)
    with open(log, "a", encoding="utf-8") as out:
        subprocess.Popen(
            ["sh", "-c", script],
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )


def sync_plugin(
    env: Mapping[str, str] | None = None,
    clock: Callable[[], float] = time.time,
    start: Callable[[list[list[str]], Path], None] = start_detached,
) -> None:
    """Install or update the plugin in the background when it is missing or old. Never
    raises."""
    env = os.environ if env is None else env
    if skills.turned_off(env):
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
        stamp = folder / "plugin-sync.json"
        now = clock()
        if tried_recently(stamp, now):
            return
        folder.mkdir(parents=True, exist_ok=True)
        stamp.write_text(json.dumps({"version": VERSION, "at": now}), "utf-8")
        start(commands(claude, found), folder / "plugin-sync.log")
    except (OSError, subprocess.SubprocessError, ValueError):
        return  # never in the way of the command that ran it
