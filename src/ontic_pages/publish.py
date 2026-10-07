"""Publish a folder or one HTML file as a new version of a page."""

from __future__ import annotations

import getpass
import json
import os
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .store import Store, check_name

META_FILE = "page.json"


def git(cwd: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=10, check=True
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip()


def strip_userinfo(url: str) -> str:
    """https://user:token@github.com/x -> https://github.com/x (never store a token)."""
    return re.sub(r"^(\w+://)[^/@]+@", r"\1", url)


def git_provenance(cwd: Path) -> dict | None:
    """Remote, branch, commit and dirty flag of the git repo at cwd, or None outside one."""
    commit = git(cwd, "rev-parse", "HEAD")
    if not commit:
        return None
    remote = git(cwd, "remote", "get-url", "origin")
    return {
        "remote": strip_userinfo(remote) if remote else None,
        "branch": git(cwd, "rev-parse", "--abbrev-ref", "HEAD"),
        "commit": commit,
        "dirty": bool(git(cwd, "status", "--porcelain")),
    }


def publisher() -> str:
    return git(Path.cwd(), "config", "user.email") or os.environ.get("USER") or getpass.getuser()


def collect(source: Path) -> dict[str, Path]:
    """Relative path -> local file. A single .html file becomes index.html. Hidden files and
    folders (.git, .DS_Store) are skipped."""
    if source.is_file():
        if source.suffix.lower() not in (".html", ".htm"):
            raise SystemExit(f"{source}: a single file must be .html; publish its folder instead")
        return {"index.html": source}
    if not source.is_dir():
        raise SystemExit(f"{source}: no such file or folder")
    files = {}
    for path in sorted(source.rglob("*")):
        rel = path.relative_to(source)
        if path.is_file() and not any(part.startswith(".") for part in rel.parts):
            files[rel.as_posix()] = path
    if not files:
        raise SystemExit(f"{source}: nothing to publish")
    if META_FILE in files:
        raise SystemExit(f"{source}: a top-level {META_FILE} is reserved for the page metadata")
    return files


def new_version(store: Store, name: str, now: datetime | None = None) -> str:
    """A UTC timestamp that is not taken yet (one second later on a clash)."""
    now = (now or datetime.now(UTC)).replace(microsecond=0)
    while True:
        version = now.strftime("%Y%m%dT%H%M%SZ")
        if not store.exists(store.key(name, version, META_FILE)):
            return version
        now += timedelta(seconds=1)


def publish(
    store: Store,
    source: Path,
    name: str,
    description: str = "",
    meta: dict[str, str] | None = None,
    cwd: Path | None = None,
    now: datetime | None = None,
) -> dict:
    """Upload the files, then page.json, then flip `current`. Returns page.json."""
    check_name(name)
    files = collect(source)
    version = new_version(store, name, now)
    for rel, path in files.items():
        with path.open("rb") as fh:
            store.put(store.key(name, version, rel), fh)
    page = {
        "name": name,
        "version": version,
        "published_at": datetime.strptime(version, "%Y%m%dT%H%M%SZ")
        .replace(tzinfo=UTC)
        .isoformat(),
        "published_by": publisher(),
        "description": description,
        "meta": dict(meta or {}),
        "git": git_provenance(cwd or Path.cwd()),
        "files": len(files),
    }
    store.put(store.key(name, version, META_FILE), json.dumps(page, indent=2).encode())
    store.set_current(name, version)
    return page
