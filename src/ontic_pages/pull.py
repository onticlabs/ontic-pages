"""`ontic-pages pull`: download a version of a page into a folder, to compare it with its source
(someone may have fixed text in the browser, see edits.py).

The gateway answers the file list with a presigned GET URL per file, so the bytes come straight
from the bucket, never through the gateway; with --direct the command reads the bucket itself.
page.json is left out: it is reserved in a folder you publish.
"""

from __future__ import annotations

import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .publish import META_FILE, check_paths
from .store import Store

URL_SECONDS = 3600
PARALLEL = 8
ATTEMPTS = 3
RETRY_SECONDS = 1.0


def presigned_files(store: Store, name: str, version: str) -> list[dict]:
    """The gateway's side: [{path, size, url}] of every file of the version but page.json."""
    prefix = store.key(name, version) + "/"
    return [
        {"path": path, "size": size, "url": store.presign_get(prefix + path, URL_SECONDS)}
        for path, size in sorted(store.sizes(prefix).items())
        if path != META_FILE
    ]


def target(dest: Path) -> Path:
    """The folder to write into: new, or empty."""
    if dest.exists() and (not dest.is_dir() or any(dest.iterdir())):
        raise SystemExit(f"{dest} exists and is not an empty folder; pick another one")
    return dest


def where(dest: Path, rel: str) -> Path:
    """dest/rel, for a path the bucket may hold (never outside dest)."""
    try:
        check_paths([rel])
    except ValueError:
        raise SystemExit(f"refusing the file path {rel!r}") from None
    path = (dest / rel).resolve()
    if not path.is_relative_to(dest.resolve()):
        raise SystemExit(f"refusing the file path {rel!r}")
    return path


def fetch(url: str, path: Path) -> None:
    """GET a presigned URL into a file, tried ATTEMPTS times."""
    for attempt in range(ATTEMPTS):
        try:
            with urllib.request.urlopen(url, timeout=300) as resp, path.open("wb") as fh:
                while chunk := resp.read(1024 * 1024):
                    fh.write(chunk)
            return
        except urllib.error.HTTPError as err:
            error = f"HTTP {err.code}"
        except (urllib.error.URLError, OSError) as err:
            error = str(getattr(err, "reason", err))
        if attempt + 1 < ATTEMPTS:
            time.sleep(RETRY_SECONDS * (attempt + 1))
    raise SystemExit(f"download of {path.name} failed {ATTEMPTS} times: {error}")


def download(files: list[dict], dest: Path, get=None) -> int:
    """Write each {path, url} (or, with `get`, get(path) -> bytes) under dest. Returns the count."""
    target(dest)
    paths = {item["path"]: where(dest, item["path"]) for item in files}
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)

    def one(item: dict) -> None:
        path = paths[item["path"]]
        if get:
            path.write_bytes(get(item["path"]))
        else:
            fetch(item["url"], path)

    with ThreadPoolExecutor(PARALLEL) as pool:
        for future in as_completed([pool.submit(one, item) for item in files]):
            future.result()
    return len(files)


def pull_direct(store: Store, name: str, version: str, dest: Path) -> int:
    prefix = store.key(name, version) + "/"
    files = [{"path": p} for p in sorted(store.sizes(prefix)) if p != META_FILE]
    return download(files, dest, get=lambda p: store.get(prefix + p)["Body"].read())


def report(name: str, page: dict, count: int, dest: Path, out=None) -> None:
    out = out or sys.stdout
    print(f"pulled {name} version {page.get('version')} ({count} files) into {dest}", file=out)
    edited = (page.get("meta") or {}).get("edited_from")
    if edited:
        by = page.get("published_by") or "someone"
        print(f"edited in the browser by {by}, from version {edited}", file=out)
