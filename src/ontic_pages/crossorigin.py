"""crossorigin="anonymous" on a page's own <img>, <video> and <audio> tags, added at publish.

Without it a browser asks for these files in no-cors mode, which direct delivery cannot
redirect to the bucket (gateway.direct_file_request), so their bytes would go through the
gateway. Only tags that load the page's own files (a relative or /-path, not http(s):, //,
data: or blob:) and have no crossorigin yet are changed; a tag in a <script> is never seen by
the parser, so code is left alone. Media made in JavaScript is the author's (SKILL.md).
"""

from __future__ import annotations

import sys
from html.parser import HTMLParser
from pathlib import Path

ATTR = ' crossorigin="anonymous"'
MAX_HTML = 5 * 1024**2


def own(url: str | None) -> bool:
    url = (url or "").strip().lower()
    return bool(url) and not url.startswith(("http:", "https:", "//", "data:", "blob:"))


class _Finder(HTMLParser):
    """Offsets right after the tag name of each tag to change."""

    def __init__(self, source: str):
        super().__init__(convert_charrefs=True)
        self.lines, at = [], 0
        for line in source.split("\n"):
            self.lines.append(at)
            at += len(line) + 1
        self.found: set[int] = set()
        self.media: int | None = None  # an open <video>/<audio> with no src, for its <source>

    def after_name(self, tag: str) -> int:
        line, col = self.getpos()
        return self.lines[line - 1] + col + 1 + len(tag)

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): v for k, v in attrs}
        if tag in ("video", "audio"):
            self.media = None
        if tag in ("img", "video", "audio") and "crossorigin" not in a:
            srcset = (a.get("srcset") or "").split(",")[0].split()
            if own(a.get("src")) or (tag == "img" and srcset and own(srcset[0])):
                self.found.add(self.after_name(tag))
            elif tag != "img" and not a.get("src"):
                self.media = self.after_name(tag)
        if tag == "source" and self.media is not None and own(a.get("src")):
            self.found.add(self.media)

    def handle_endtag(self, tag):
        if tag in ("video", "audio"):
            self.media = None


def add_crossorigin(source: str) -> tuple[str, int]:
    """The HTML with the attribute added, and how many tags got it."""
    finder = _Finder(source)
    finder.feed(source)
    finder.close()
    for at in sorted(finder.found, reverse=True):
        source = source[:at] + ATTR + source[at:]
    return source, len(finder.found)


def fix_media(files: dict[str, Path], tmp: Path, out=None) -> int:
    """Patch the HTML files among `files` (relative path -> local file) into `tmp` and point
    `files` at the patched copies; the originals are not changed. Says what it did on `out`
    (stderr). Returns how many tags were changed."""
    out = out or sys.stderr
    total = 0
    for rel, path in list(files.items()):
        if not rel.lower().endswith((".html", ".htm")) or path.stat().st_size > MAX_HTML:
            continue
        try:
            source = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            continue
        patched, n = add_crossorigin(source)
        if n:
            copy = tmp / rel
            copy.parent.mkdir(parents=True, exist_ok=True)
            copy.write_bytes(patched.encode("utf-8"))
            files[rel] = copy
            total += n
            tags = "tag" if n == 1 else "tags"
            print(f'{rel}: added crossorigin="anonymous" to {n} image/video/audio {tags}', file=out)
    return total
