"""Comments on a page: threads pinned to a point on it, with replies, resolve and reopen.

One JSON file per page in the bucket, next to `current` and `visibility`:

    <prefix><name>/comments.json
    {"threads": [{"id", "version", "anchor", "created_by", "created_at", "resolved_at",
                  "resolved_by", "comments": [{"id", "author", "body", "created_at",
                  "deleted"}]}]}

It cannot collide with anything else of the page: versions are timestamps (VERSION_RE) and a
version's files sit under <version>/. The gateway is its only writer: every change reads,
changes and writes the whole file under the page's lock. The file is kept in memory and read
again from the bucket at most every `ttl` seconds. Overwriting it is the only write (the bucket
keeps the old copies); nothing is deleted. A deleted comment stays as a tombstone (deleted,
body emptied), so the replies around it keep their place.

An anchor is where a thread points, as the bridge (static/pins.js) computed it: path (on the
page, without /_v/<version>), selector (a CSS path, at most 8 levels), fx and fy (the point
within that element's box, 0 to 1), snippet (the element's text, at most 60 characters) and x, y
(document pixels, the fallback for threads made on the version being viewed).
"""

from __future__ import annotations

import copy
import json
import math
import re
import secrets
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime

from .store import Store
from .uploads import Refused

FILE = "comments.json"
BODY_LIMIT = 4000
SNIPPET_LIMIT = 60
SELECTOR_LIMIT = 1024
SELECTOR_LEVELS = 8
PATH_LIMIT = 1024
MAX_THREADS = 1000
MAX_COMMENTS = 200
ID_RE = re.compile(r"^[0-9a-f]{16}$")
# Control characters but newline and tab (after CRLF is normalized), and the bidirectional
# overrides that make text read differently from what it is.
CONTROL = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]")


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_id() -> str:
    return secrets.token_hex(8)


def clean_body(value) -> str:
    """The text of a comment: line endings normalized, control characters removed, trimmed,
    1 to BODY_LIMIT characters. Stored and shown as plain text only."""
    if not isinstance(value, str):
        raise Refused(400, "body: the comment, as text")
    text = CONTROL.sub("", value.replace("\r\n", "\n").replace("\r", "\n")).strip()
    if not text:
        raise Refused(400, "the comment is empty")
    if len(text) > BODY_LIMIT:
        raise Refused(400, f"a comment is at most {BODY_LIMIT} characters")
    return text


def _number(value, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise Refused(400, f"anchor {what}: a number")
    return float(value)


def _text(value, what: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise Refused(400, f"anchor {what}: text")
    return CONTROL.sub("", value)


def clean_anchor(value) -> dict:
    """Only the known fields, checked: strings cut, numbers clamped. A selector that is too
    long or too deep is dropped (the pin then falls back to x, y)."""
    if not isinstance(value, dict):
        raise Refused(400, "anchor: {path, selector, fx, fy, snippet, x, y}")
    path = _text(value.get("path"), "path") or "/"
    if not path.startswith("/") or path.startswith("//") or len(path) > PATH_LIMIT:
        raise Refused(400, "anchor path: a path on the page, starting with /")
    selector = _text(value.get("selector"), "selector").strip()
    if len(selector) > SELECTOR_LIMIT or selector.count(">") >= SELECTOR_LEVELS:
        selector = ""
    snippet = " ".join(_text(value.get("snippet"), "snippet")[: 8 * SNIPPET_LIMIT].split())
    return {
        "path": path,
        "selector": selector,
        "fx": round(min(1.0, max(0.0, _number(value.get("fx", 0.5), "fx"))), 4),
        "fy": round(min(1.0, max(0.0, _number(value.get("fy", 0.5), "fy"))), 4),
        "snippet": snippet[:SNIPPET_LIMIT],
        "x": round(min(1e7, max(0.0, _number(value.get("x", 0), "x"))), 1),
        "y": round(min(1e7, max(0.0, _number(value.get("y", 0), "y"))), 1),
    }


def display_name(email: str) -> str:
    """mikel.zhobro@onticlabs.io -> Mikel Zhobro."""
    local = (email or "").split("@")[0]
    words = [w for w in re.split(r"[._+-]+", local) if w]
    return " ".join(w[:1].upper() + w[1:] for w in words) or email or ""


def same(a: str | None, b: str | None) -> bool:
    return (a or "").strip().lower() == (b or "").strip().lower()


def view(thread: dict, email: str) -> dict:
    """A thread as the API answers it: names next to the emails, `resolved`, `updated_at`, and
    `mine` on each comment (the caller wrote it)."""
    comments = []
    for c in thread.get("comments", []):
        author = c.get("author", "")
        comments.append({**c, "author_name": display_name(author), "mine": same(author, email)})
    moments = [thread.get("created_at") or "", thread.get("resolved_at") or ""]
    moments += [c.get("created_at") or "" for c in comments]
    resolved_by = thread.get("resolved_by") or ""
    return {
        **thread,
        "created_by_name": display_name(thread.get("created_by", "")),
        "resolved": bool(thread.get("resolved_at")),
        "resolved_by_name": display_name(resolved_by) if resolved_by else "",
        "updated_at": max(moments),
        "comments": comments,
    }


def listing(threads: list[dict], email: str) -> list[dict]:
    """Every thread as the API answers it, newest activity first."""
    views = [view(t, email) for t in threads]
    views.sort(key=lambda t: (t["updated_at"], t.get("created_at") or ""), reverse=True)
    return views


def parse(text: str | None) -> dict:
    if text is None:
        return {"threads": []}
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if not isinstance(data, dict) or not isinstance(data.get("threads"), list):
        raise Refused(502, "the page's comments file cannot be read")
    return data


def _thread(threads: list[dict], thread_id: str) -> dict:
    for thread in threads:
        if thread.get("id") == thread_id:
            return thread
    raise Refused(404, "no such comment thread on this page")


class Comments:
    """Every page's comments.json: read through a cache of `ttl` seconds, changed under a
    lock per page. A cached file is never changed in place (a change works on a copy and then
    replaces it), so readers may keep what they got."""

    def __init__(self, store: Store, ttl: float = 5.0):
        self.store, self.ttl = store, ttl
        self.lock = threading.Lock()
        self.locks: dict[str, threading.Lock] = {}
        self.cache: dict[str, tuple[float, dict]] = {}

    def _page_lock(self, name: str) -> threading.Lock:
        with self.lock:
            return self.locks.setdefault(name, threading.Lock())

    def _read(self, name: str) -> dict:
        """Under the page's lock."""
        moment = time.monotonic()
        hit = self.cache.get(name)
        if hit and moment - hit[0] < self.ttl:
            return hit[1]
        data = parse(self.store.read_text(self.store.key(name, FILE)))
        self.cache[name] = (moment, data)
        return data

    def threads(self, name: str) -> list[dict]:
        with self._page_lock(name):
            return self._read(name)["threads"]

    def _change(self, name: str, change: Callable[[list[dict]], tuple[dict, bool]]) -> dict:
        """change(threads) -> (the thread, whether anything changed); written only then."""
        with self._page_lock(name):
            data = copy.deepcopy(self._read(name))
            thread, changed = change(data["threads"])
            if changed:
                body = json.dumps(data, indent=1).encode()
                self.store.put(self.store.key(name, FILE), body)
                self.cache[name] = (time.monotonic(), data)
            return thread

    def create(self, name: str, version: str, anchor, author: str, body) -> dict:
        anchor, body = clean_anchor(anchor), clean_body(body)

        def change(threads):
            if len(threads) >= MAX_THREADS:
                raise Refused(409, f"a page takes at most {MAX_THREADS} comment threads")
            when = now()
            thread = {
                "id": new_id(),
                "version": version,
                "anchor": anchor,
                "created_by": author,
                "created_at": when,
                "resolved_at": None,
                "resolved_by": None,
                "comments": [comment(author, body, when)],
            }
            threads.append(thread)
            return thread, True

        return self._change(name, change)

    def reply(self, name: str, thread_id: str, author: str, body) -> dict:
        body = clean_body(body)

        def change(threads):
            thread = _thread(threads, thread_id)
            if len(thread["comments"]) >= MAX_COMMENTS:
                raise Refused(409, f"a thread takes at most {MAX_COMMENTS} comments")
            thread["comments"].append(comment(author, body, now()))
            return thread, True

        return self._change(name, change)

    def resolve(self, name: str, thread_id: str, resolved: bool, by: str) -> dict:
        def change(threads):
            thread = _thread(threads, thread_id)
            if bool(thread.get("resolved_at")) == resolved:
                return thread, False
            thread["resolved_at"] = now() if resolved else None
            thread["resolved_by"] = by if resolved else None
            return thread, True

        return self._change(name, change)

    def delete(self, name: str, thread_id: str, comment_id: str, by: str) -> dict:
        """Only its author deletes a comment: it stays, marked deleted, without its text."""

        def change(threads):
            thread = _thread(threads, thread_id)
            for item in thread["comments"]:
                if item.get("id") == comment_id:
                    break
            else:
                raise Refused(404, "no such comment in this thread")
            if not same(item.get("author"), by):
                raise Refused(403, "only its author can delete a comment")
            if item.get("deleted"):
                return thread, False
            item["deleted"], item["body"] = True, ""
            return thread, True

        return self._change(name, change)


def comment(author: str, body: str, when: str) -> dict:
    return {"id": new_id(), "author": author, "body": body, "created_at": when, "deleted": False}
