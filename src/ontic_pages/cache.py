"""What the gateway keeps in memory.

A version never changes once written, so its files are kept (least recently used out first) by
(name, version, path). Only `current`, `visibility` and the list of versions can change; they are
kept for a few seconds.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

from .store import Store

MB = 1024 * 1024


@dataclass(frozen=True)
class File:
    etag: str  # a strong ETag, quoted, from the version and the bucket's ETag
    size: int
    data: bytes | None  # None when the file is over the per-file cap: stream it instead


class FileCache:
    def __init__(self, store: Store, max_bytes: int = 256 * MB, max_file: int = 4 * MB):
        self.store, self.max_bytes, self.max_file = store, max_bytes, max_file
        self.lock = threading.Lock()
        self.files: OrderedDict[tuple[str, str, str], File] = OrderedDict()
        self.total = 0

    def get(self, name: str, version: str, path: str):
        """(File, open body or None), or None when the file does not exist. The body is open
        only for a big file fetched just now; the caller closes it. For a big file seen before,
        only its size and ETag are kept and there is no body: fetch it again to send it."""
        key = (name, version, path)
        with self.lock:
            hit = self.files.get(key)
            if hit:
                self.files.move_to_end(key)
                return hit, None
        obj = self.store.get(self.store.key(name, version, path))
        if obj is None:
            return None
        size, body = obj["ContentLength"], obj["Body"]
        data = None
        if size <= self.max_file:
            try:
                data = body.read()
            finally:
                body.close()
            body = None
        tag = (obj.get("ETag") or "").strip('"') or hashlib.sha256(data or b"").hexdigest()[:32]
        entry = File(f'"{version}-{tag}"', size, data)
        with self.lock:
            if key not in self.files:
                self.files[key] = entry
                self.total += len(data or b"")
            while self.total > self.max_bytes and self.files:
                _, old = self.files.popitem(last=False)
                self.total -= len(old.data or b"")
        return entry, body

    def meta(self, name: str, version: str) -> dict:
        found = self.get(name, version, "page.json")
        if found is None or found[0].data is None:
            return {}
        return json.loads(found[0].data)


class PageCache:
    """(current version, visibility, owner) and the versions of each page, kept for `ttl`
    seconds so a page with many assets costs one lookup. The owner is the current version's
    published_by."""

    def __init__(self, store: Store, files: FileCache, ttl: float):
        self.store, self.files, self.ttl = store, files, ttl
        self.lock = threading.Lock()
        self.entries: dict[str, tuple[float, tuple]] = {}
        self.lists: dict[str, tuple[float, list[str]]] = {}

    def get(self, name: str) -> tuple[str | None, str, str]:
        now = time.monotonic()
        with self.lock:
            hit = self.entries.get(name)
        if hit and now - hit[0] < self.ttl:
            return hit[1]
        version = self.store.current(name)
        visibility = self.store.visibility(name)
        owner = self.files.meta(name, version).get("published_by", "") if version else ""
        value = (version, visibility, owner)
        with self.lock:
            self.entries[name] = (now, value)
        return value

    def versions(self, name: str) -> list[str]:
        """Oldest first, like Store.versions."""
        now = time.monotonic()
        with self.lock:
            hit = self.lists.get(name)
        if hit and now - hit[0] < self.ttl:
            return hit[1]
        versions = self.store.versions(name)
        with self.lock:
            self.lists[name] = (now, versions)
        return versions

    def forget(self, name: str) -> None:
        with self.lock:
            self.entries.pop(name, None)
            self.lists.pop(name, None)
