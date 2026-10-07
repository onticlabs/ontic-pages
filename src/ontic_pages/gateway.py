"""A small read-only web server for the pages in the bucket.

    GET /                        a listing of the pages this viewer may open
    GET /<name>/<path>           <prefix><name>/<current>/<path>, index.html for folders
    GET /<name>/_info            what page.json says about the page, and its versions
    GET /public/<name>/<path>    the same, for public pages only; others redirect to /<name>/...
                                 (and so does /public/<name>/_info: metadata stays signed in)
    GET /_health                 "ok"

Sign-in is not done here. In production Caddy sends /public/* and /_health straight to the
gateway and everything else through oauth2-proxy, which sets X-Forwarded-Email. The gateway
only routes on that header:

    public   anyone (on /public/<name>/ without sign-in, on /<name>/ signed in)
    ontic    X-Forwarded-Email ends with @<email domain>
    private  X-Forwarded-Email is the current version's published_by
"""

from __future__ import annotations

import html
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, unquote, urlsplit

from botocore.exceptions import ClientError

from .info import DESCRIPTION_CHARS, NAME_CHARS, history, info_html, short
from .store import NAME_RE, RESERVED_NAMES, Store, content_type

CHUNK = 256 * 1024


class PageCache:
    """(current version, visibility, owner) per page, kept for a few seconds so a page with
    many assets costs one lookup. The owner (published_by) is read only for private pages."""

    def __init__(self, store: Store, ttl: float):
        self.store, self.ttl = store, ttl
        self.lock = threading.Lock()
        self.entries: dict[str, tuple[float, tuple]] = {}

    def get(self, name: str) -> tuple[str | None, str, str]:
        now = time.monotonic()
        with self.lock:
            hit = self.entries.get(name)
        if hit and now - hit[0] < self.ttl:
            return hit[1]
        version = self.store.current(name)
        visibility = self.store.visibility(name)
        owner = ""
        if version and visibility == "private":
            owner = self.store.meta(name, version).get("published_by", "")
        value = (version, visibility, owner)
        with self.lock:
            self.entries[name] = (now, value)
        return value


def allowed(visibility: str, owner: str, email: str, domain: str) -> bool:
    email = email.strip().lower()
    if visibility == "public":
        return True
    if visibility == "private":
        return bool(email) and email == owner.strip().lower()
    return bool(email) and (not domain or email.endswith("@" + domain.lower()))


BADGE_CSS = """
.badge { font-size: .75rem; padding: .05rem .4rem; border-radius: .6rem; border: 1px solid; }
.private { color: #a33; } .ontic { color: #555; } .public { color: #276; }
"""


def listing_html(store: Store, cache: PageCache, email: str, domain: str) -> str:
    rows = []
    for name in store.names():
        version, visibility, _ = cache.get(name)
        if not version:
            continue
        meta = store.meta(name, version)
        owner = meta.get("published_by", "")
        if not allowed(visibility, owner, email, domain):
            continue
        link = f"/{quote(name)}/"
        public = (
            f' <a href="/public/{quote(name)}/">public link</a>' if visibility == "public" else ""
        )
        cells = [
            f'<a href="{link}">{short(name, NAME_CHARS)}</a>',
            f'<span class="badge {visibility}">{visibility}</span>{public}',
            short(meta.get("description", ""), DESCRIPTION_CHARS),
            html.escape(meta.get("published_at", version)[:16].replace("T", " ")),
            html.escape(owner),
            f'<a href="/{quote(name)}/_info">info</a>',
        ]
        rows.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    body = "\n".join(rows) or '<tr><td colspan="6">No pages yet.</td></tr>'
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Ontic pages</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body {{ font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 70rem; padding: 0 1rem; }}
table {{ border-collapse: collapse; width: 100%; }}
td, th {{ text-align: left; padding: .4rem .6rem; border-bottom: 1px solid #ddd; }}
td {{ white-space: nowrap; }}
{BADGE_CSS}
</style></head><body>
<h1>Ontic pages</h1>
<table><tr><th>Page</th><th>Visibility</th><th>Description</th><th>Published</th><th>By</th><th></th></tr>
{body}
</table></body></html>
"""


def make_handler(store: Store, cache: PageCache, domain: str, local_email: str = ""):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ontic-pages"

        def email(self) -> str:
            sent = (self.headers.get("X-Forwarded-Email") or "").strip() if self.headers else ""
            return sent or local_email

        def log_message(self, fmt, *args):
            who = self.email() or "-"
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

        def redirect(self, location: str, code: int = 301):
            self.send_response(code)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def forbidden(self, name: str, visibility: str):
            who = "its publisher" if visibility == "private" else f"@{domain} accounts"
            self.send_text(
                403,
                f"<!doctype html><title>Not allowed</title><p>{html.escape(name)} is a "
                f"{visibility} page, open to {html.escape(who)} only.</p>\n",
                "text/html; charset=utf-8",
            )

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            url = urlsplit(self.path)
            path = unquote(url.path)
            query = f"?{url.query}" if url.query else ""
            if path == "/":
                page = listing_html(store, cache, self.email(), domain)
                return self.send_text(200, page, "text/html; charset=utf-8")
            if path == "/_health":
                return self.send_text(200, "ok\n")
            public = path.startswith("/public/")
            base = "/public/" if public else "/"
            name, slash, rest = path[len(base) :].partition("/")
            if not NAME_RE.match(name) or name in RESERVED_NAMES:
                return self.send_text(404, "not found\n")
            if not slash:
                return self.redirect(f"{base}{quote(name)}/{query}")
            if any(p in (".", "..") or "\\" in p for p in rest.split("/")):
                return self.send_text(404, "not found\n")
            version, visibility, owner = cache.get(name)
            if not version:
                return self.send_text(404, f"no page named {name}\n")
            if public and (visibility != "public" or rest == "_info"):
                return self.redirect(f"/{quote(name)}/{quote(rest)}{query}", 302)
            if not public and not allowed(visibility, owner, self.email(), domain):
                return self.forbidden(name, visibility)
            if rest == "_info":
                page = info_html(name, *history(store, name), visibility)
                return self.send_text(200, page, "text/html; charset=utf-8")
            if rest == "" or rest.endswith("/"):
                rest += "index.html"
            try:
                obj = store.get(store.key(name, version, rest), self.headers.get("Range"))
                if obj is None and not rest.endswith("index.html"):
                    if store.exists(store.key(name, version, rest, "index.html")):
                        return self.redirect(f"{base}{quote(name)}/{quote(rest)}/{query}")
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


def make_server(
    store: Store,
    host: str,
    port: int,
    ttl: float = 5.0,
    email_domain: str = "onticlabs.io",
    local_email: str = "",
) -> ThreadingHTTPServer:
    handler = make_handler(store, PageCache(store, ttl), email_domain, local_email)
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server


def serve(
    store: Store, host: str, port: int, ttl: float, email_domain: str, local_email: str = ""
) -> None:
    server = make_server(store, host, port, ttl, email_domain, local_email)
    print(f"serving {store.bucket}/{store.prefix} on http://{host}:{server.server_port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
