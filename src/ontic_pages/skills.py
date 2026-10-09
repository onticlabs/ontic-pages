"""The ontic-pages agent skill, installed for Claude Code and Codex on every run.

The skill text is package data (`skills/ontic-pages/SKILL.md`). Every command except `gateway`
and `skill` calls `sync_skill`, which copies it to `<CLAUDE_CONFIG_DIR or ~/.claude>/skills/` and
`<CODEX_HOME or ~/.codex>/skills/` when those agent folders exist (they are never created), so a
reinstall of the tool, which runs no code, still reaches the agents on the next run.

The installed copy carries a marker line after the frontmatter. A file with our marker (or the
one ontic-cli 0.29.0 wrote) is ours and is rewritten when it differs; a file without one is the
user's and is left alone, unless it is exactly the bundled text. A symlinked SKILL.md is left
alone. The sync costs a stat and a small read per target, prints only on a first install (to
stderr) and never raises. `ONTIC_AGENT_SKILLS=0` turns it off.
"""

from __future__ import annotations

import contextlib
import os
import sys
from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path

NAME = "ontic-pages"
MARKER = (
    "<!-- managed by ontic-pages: updated on every run; delete this line to keep your own "
    "edits, ONTIC_AGENT_SKILLS=0 to stop -->"
)
# What ontic-cli 0.29.0 put in the copies it installed; those are ours too.
CLI_MARKER = (
    "<!-- managed by ontic-cli: edits are overwritten on update, "
    "set ONTIC_AGENT_SKILLS=0 to stop -->"
)
OPT_OUT = "ONTIC_AGENT_SKILLS"

CURRENT = "installed and current"
OUTDATED = "outdated (rewritten on the next run)"
MISSING = "not installed (installed on the next run)"
YOURS = "yours (no marker, left alone)"
SYMLINK = "symlink, left alone"
NO_AGENT = "no agent folder"
OFF = "turned off (ONTIC_AGENT_SKILLS=0)"


def bundled() -> str:
    """The skill text shipped in the package."""
    return (files("ontic_pages") / "skills" / NAME / "SKILL.md").read_text(encoding="utf-8")


def installed_text(text: str) -> str:
    """`text` with the marker on its own line right after the closing `---` of the frontmatter,
    so the agents still read the frontmatter first; before everything without one."""
    lines = text.splitlines(keepends=True)
    if lines and lines[0].rstrip("\r\n") == "---":
        for i in range(1, len(lines)):
            if lines[i].rstrip("\r\n") == "---":
                end = "\r\n" if lines[i].endswith("\r\n") else "\n"
                if not lines[i].endswith(("\n", "\r")):
                    lines[i] += end
                return "".join(lines[: i + 1] + [MARKER + end] + lines[i + 1 :])
    return f"{MARKER}\n{text}"


def turned_off(env: Mapping[str, str]) -> bool:
    return env.get(OPT_OUT, "").strip().lower() in ("0", "false", "no", "off")


def targets(env: Mapping[str, str] | None = None) -> list[tuple[str, Path, Path]]:
    """(agent, agent folder, SKILL.md path) for Claude Code and Codex."""
    env = os.environ if env is None else env
    homes = (
        ("Claude Code", env.get("CLAUDE_CONFIG_DIR") or "~/.claude"),
        ("Codex", env.get("CODEX_HOME") or "~/.codex"),
    )
    out = []
    for agent, home in homes:
        root = Path(home).expanduser()
        out.append((agent, root, root / "skills" / NAME / "SKILL.md"))
    return out


def state(root: Path, target: Path, text: str, wanted: str) -> str:
    """One of the states above (all but OFF) for one target; may raise OSError."""
    if not root.is_dir():
        return NO_AGENT
    if target.is_symlink():
        return SYMLINK
    try:
        current = target.read_bytes().decode("utf-8", errors="replace")
    except FileNotFoundError:
        return MISSING
    if current == wanted:
        return CURRENT
    if MARKER in current or CLI_MARKER in current or current == text:
        return OUTDATED
    return YOURS


def write_atomic(target: Path, text: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        temp.write_bytes(text.encode("utf-8"))
        os.replace(temp, target)
    finally:
        with contextlib.suppress(OSError):
            temp.unlink(missing_ok=True)


def sync_skill(env: Mapping[str, str] | None = None) -> None:
    """Install or refresh the skill for each agent whose folder exists. Never raises."""
    env = os.environ if env is None else env
    if turned_off(env):
        return
    try:
        text = bundled()
    except OSError:
        return
    wanted = installed_text(text)
    for agent, root, target in targets(env):
        try:
            found = state(root, target, text, wanted)
            if found in (MISSING, OUTDATED):
                write_atomic(target, wanted)
                if found == MISSING:
                    print(
                        f"installed the {NAME} agent skill for {agent} at {target} "
                        f"({OPT_OUT}=0 to stop)",
                        file=sys.stderr,
                    )
        except OSError:
            continue


def status(env: Mapping[str, str] | None = None) -> list[tuple[str, Path, str]]:
    """(agent, SKILL.md path, state) for each target."""
    env = os.environ if env is None else env
    text = bundled()
    wanted = installed_text(text)
    out = []
    for agent, root, target in targets(env):
        if turned_off(env):
            found = OFF
        else:
            try:
                found = state(root, target, text, wanted)
            except OSError as err:
                found = f"unreadable ({err.strerror or err})"
        out.append((agent, target, found))
    return out


def install(env: Mapping[str, str] | None = None) -> list[tuple[str, Path, str]]:
    """Write ours to each agent that has a folder, over any regular file (never over a
    symlink); ONTIC_AGENT_SKILLS=0 does not stop it. Returns (agent, path, what happened)."""
    wanted = installed_text(bundled())
    out = []
    for agent, root, target in targets(env):
        try:
            if not root.is_dir():
                done = NO_AGENT
            elif target.is_symlink():
                done = SYMLINK
            elif target.is_file() and target.read_bytes().decode("utf-8", "replace") == wanted:
                done = CURRENT
            else:
                write_atomic(target, wanted)
                done = "installed"
        except OSError as err:
            done = f"failed ({err.strerror or err})"
        out.append((agent, target, done))
    return out
