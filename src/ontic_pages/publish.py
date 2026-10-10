"""Publish a folder or one HTML file as a new version of a page."""

from __future__ import annotations

import getpass
import json
import os
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .store import Store, check_name, check_visibility

META_FILE = "page.json"
MAX_PATH_BYTES = 900  # S3 keys are at most 1024 bytes, with the name and version in front


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
    try:
        check_paths(files)
    except ValueError as err:
        raise SystemExit(f"{source}: {err}") from None
    return files


def check_paths(paths) -> None:
    """The file paths a version may have (the gateway checks them too): relative, no '.', '..',
    empty or hidden parts, and nothing the gateway answers itself."""
    for rel in paths:
        parts = rel.split("/")
        if (
            not rel
            or len(rel.encode()) > MAX_PATH_BYTES
            or "\\" in rel
            or any(not p or p in (".", "..") or p.startswith(".") for p in parts)
            or any(ord(c) < 32 or ord(c) == 127 for c in rel)
        ):
            raise ValueError(f"bad file path {rel!r}")
        if rel in (META_FILE, "_info"):
            raise ValueError(f"a top-level {rel} is reserved by ontic-pages")
        if parts[0] == "_v":
            raise ValueError("a top-level _v folder is reserved by ontic-pages (versions)")


def new_version(
    store: Store, name: str, now: datetime | None = None, taken: set[str] | None = None
) -> str:
    """A UTC timestamp that is not taken yet (one second later on a clash). `taken`: versions
    already promised to an upload that has not finished."""
    now = (now or datetime.now(UTC)).replace(microsecond=0)
    while True:
        version = now.strftime("%Y%m%dT%H%M%SZ")
        if version not in (taken or ()) and not store.exists(store.key(name, version, META_FILE)):
            return version
        now += timedelta(seconds=1)


def page_record(
    name: str,
    version: str,
    published_by: str,
    description: str,
    meta: dict,
    git: dict | None,
    files: int,
) -> dict:
    """page.json of a version."""
    return {
        "name": name,
        "version": version,
        "published_at": datetime.strptime(version, "%Y%m%dT%H%M%SZ")
        .replace(tzinfo=UTC)
        .isoformat(),
        "published_by": published_by,
        "description": description,
        "meta": dict(meta or {}),
        "git": git,
        "files": files,
    }


def page_json(page: dict) -> bytes:
    """page.json as written to the bucket."""
    return json.dumps(page, indent=2).encode()


def finish(store: Store, page: dict, visibility: str | None) -> str:
    """After the files: page.json, then the visibility (only when given; a later publish without
    it keeps the level), then flip `current`. Returns page.json's ETag (may be empty)."""
    name, version = page["name"], page["version"]
    etag = store.put(store.key(name, version, META_FILE), page_json(page))
    if visibility is not None:
        store.set_visibility(name, visibility)
    store.set_current(name, version)
    return etag


def publish(
    store: Store,
    source: Path,
    name: str,
    description: str = "",
    meta: dict[str, str] | None = None,
    visibility: str | None = None,
    published_by: str | None = None,
    cwd: Path | None = None,
    now: datetime | None = None,
) -> dict:
    """Upload the files, then page.json, then the visibility (only when given; a later publish
    without it keeps the level), then flip `current`. Returns page.json."""
    check_name(name)
    if visibility is not None:
        check_visibility(visibility)
    files = collect(source)
    version = new_version(store, name, now)
    for rel, path in files.items():
        with path.open("rb") as fh:
            store.put(store.key(name, version, rel), fh)
    page = page_record(
        name, version, published_by or publisher(), description, meta or {},
        git_provenance(cwd or Path.cwd()), len(files),
    )  # fmt: skip
    finish(store, page, visibility)
    return page
