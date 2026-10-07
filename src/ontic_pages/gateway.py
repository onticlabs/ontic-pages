"""A small read-only web server for the pages in the bucket.

    GET /                 a plain listing of every page
    GET /<name>/<path>    the file from <prefix><name>/<current>/<path>; index.html for folders
    GET /_health          "ok"

Sign-in is not done here: in production the gateway sits behind oauth2-proxy and Caddy, and
X-Forwarded-Email is only written to the log.
"""

from __future__ import annotations

import html
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, unquote, urlsplit

from botocore.exceptions import ClientError

from .store import NAME_RE, Store, content_type

CHUNK = 256 * 1024


class CurrentCache:
    """`current` per page, kept for a few seconds so a page with many assets costs one lookup."""

    def __init__(self, store: Store, ttl: float):
        self.store, self.ttl = store, ttl
        self.lock = threading.Lock()
        self.entries: dict[str, tuple[float, str | None]] = {}

    def get(self, name: str) -> str | None:
        now = time.monotonic()
        with self.lock:
            hit = self.entries.get(name)
        if hit and now - hit[0] < self.ttl:
            return hit[1]
        version = self.store.current(name)
        with self.lock:
            self.entries[name] = (now, version)
        return version


def listing_html(store: Store, cache: CurrentCache) -> str:
    rows = []
    for name in store.names():
        version = cache.get(name)
        if not version:
            continue
        meta = store.meta(name, version)
        cells = [
            f'<a href="/{quote(name)}/">{html.escape(name)}</a>',
            html.escape(meta.get("description", "")),
            html.escape(meta.get("published_at", version)),
            html.escape(meta.get("published_by", "")),
        ]
        rows.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    body = "\n".join(rows) or '<tr><td colspan="4">No pages yet.</td></tr>'
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Ontic pages</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body {{ font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 60rem; padding: 0 1rem; }}
table {{ border-collapse: collapse; width: 100%; }}
td, th {{ text-align: left; padding: .4rem .6rem; border-bottom: 1px solid #ddd; }}
</style></head><body>
<h1>Ontic pages</h1>
<table><tr><th>Page</th><th>Description</th><th>Published</th><th>By</th></tr>
{body}
</table></body></html>
"""


def make_handler(store: Store, cache: CurrentCache):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ontic-pages"

        def log_message(self, fmt, *args):
            who = self.headers.get("X-Forwarded-Email", "-") if self.headers else "-"
            sys.stderr.write(f"{self.log_date_time_string()} {who} {fmt % args}\n")

        def send_text(self, code: int, text: str, ctype="text/plain; charset=utf-8"):
            body = text.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def redirect(self, location: str):
            self.send_response(301)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            url = urlsplit(self.path)
            path = unquote(url.path)
            query = f"?{url.query}" if url.query else ""
            if path == "/":
                return self.send_text(200, listing_html(store, cache), "text/html; charset=utf-8")
            if path == "/_health":
                return self.send_text(200, "ok\n")
            name, slash, rest = path[1:].partition("/")
            if not NAME_RE.match(name):
                return self.send_text(404, "not found\n")
            if not slash:
                return self.redirect(f"/{quote(name)}/{query}")
            parts = rest.split("/")
            if any(p in (".", "..") or "\\" in p for p in parts):
                return self.send_text(404, "not found\n")
            version = cache.get(name)
            if not version:
                return self.send_text(404, f"no page named {name}\n")
            if rest == "" or rest.endswith("/"):
                rest += "index.html"
            try:
                obj = store.get(store.key(name, version, rest), self.headers.get("Range"))
                if obj is None and not rest.endswith("index.html"):
                    if store.exists(store.key(name, version, rest, "index.html")):
                        return self.redirect(f"/{quote(name)}/{quote(rest)}/{query}")
            except ClientError as err:
                if err.response.get("Error", {}).get("Code") == "InvalidRange":
                    return self.send_text(416, "range not satisfiable\n")
                self.log_error("store error: %s", err)
                return self.send_text(502, "store error\n")
            if obj is None:
                return self.send_text(404, "not found\n")
            self.send_file(obj, rest)

        def send_file(self, obj: dict, rest: str):
            self.send_response(206 if obj.get("ContentRange") else 200)
            self.send_header("Content-Type", content_type(rest))
            self.send_header("Content-Length", str(obj["ContentLength"]))
            if obj.get("ContentRange"):
                self.send_header("Content-Range", obj["ContentRange"])
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            body = obj["Body"]
            try:
                while self.command != "HEAD" and (chunk := body.read(CHUNK)):
                    self.wfile.write(chunk)
            finally:
                body.close()

    return Handler


def make_server(store: Store, host: str, port: int, ttl: float = 5.0) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), make_handler(store, CurrentCache(store, ttl)))
    server.daemon_threads = True
    return server


def serve(store: Store, host: str, port: int, ttl: float = 5.0) -> None:
    server = make_server(store, host, port, ttl)
    print(f"serving {store.bucket}/{store.prefix} on http://{host}:{server.server_port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
