"""The gateway: a small web server for the pages in the bucket.

On the apex (the host of ONTIC_PAGES_URL, pages.onticlabs.io):

    GET  /                              a listing of the pages this viewer may open
    GET  /<name>/<path>                 the shell: the bar, and a frame showing <path> from the
                                        page's own host
    GET  /<name>/_v/<version>/<path>    the same, for one version
    GET  /<name>/_info                  what page.json says about the page, and its versions
    GET  /public/<name>/<path>          old links: redirects to /<name>/<path>
    GET  /_api/pages/<name>             the page facts this viewer may see, as JSON
    POST /_api/pages/<name>/visibility  {"visibility": ...}, by the owner only
    GET  /_bar/bar.<hash>.js|css        the shell's script and style

On a page's own host, <name>.<content suffix> (the content host):

    GET  /<path>                        the current version's file, index.html for folders
    GET  /_v/<version>/<path>           a given version's file
    GET  /_bridge.<hash>.js             the bridge, added to HTML shown in the shell's frame

    A browser opening a content URL as a page of its own (Sec-Fetch-Dest: document) is sent to
    the shell, unless the URL has ?raw=1 or the page itself navigated there.

On any host: GET /_health. On other hosts only (Caddy asks on 127.0.0.1): GET /_tls-ask?domain=.

Who is asking comes from oauth2-proxy (auth.py), never from request headers. Access, checked
before every answer: public anyone, ontic an @<email domain> address, private the current
version's publisher. Writes go to the apex only, from the apex only (Sec-Fetch-Site, Origin).
"""

from __future__ import annotations

import html
import json
import re
import sys
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlsplit

from botocore.exceptions import ClientError

from .auth import (
    DEFAULT_AUTH_URL,
    Identity,
    IdentityUnavailable,
    OAuth2Proxy,
    RateLimit,
    allowed,
    fixed,
)
from .cache import MB, FileCache, PageCache
from .config import DEFAULT_URL
from .info import DESCRIPTION_CHARS, NAME_CHARS, history, info_html, short
from .shell import Assets, inject, shell_csp, shell_html
from .store import NAME_RE, RESERVED_NAMES, VISIBILITIES, Store, content_type

CHUNK = 256 * 1024
YEAR = "max-age=31536000, immutable"
VERSIONED = re.compile(r"^_v/(\d{8}T\d{6}Z)(/.*)?$")
API_PAGE = re.compile(r"^/_api/pages/([^/]+)$")
API_VISIBILITY = re.compile(r"^/_api/pages/([^/]+)/visibility$")
PLAIN_CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; "
    "form-action 'none'"
)


@dataclass(frozen=True)
class Site:
    """Where the gateway answers: url is the apex (scheme and host), and each page's content
    lives at <name>.<suffix> (the apex host when suffix is empty)."""

    url: str = DEFAULT_URL
    suffix: str = ""
    email_domain: str = "onticlabs.io"

    @property
    def apex(self) -> str:
        return urlsplit(self.url).netloc.lower()

    @property
    def scheme(self) -> str:
        return urlsplit(self.url).scheme or "https"

    @property
    def origin(self) -> str:
        return f"{self.scheme}://{self.apex}"

    @property
    def content_suffix(self) -> str:
        return (self.suffix or self.apex).lower().strip(".")

    def content_origin(self, name: str) -> str:
        return f"{self.scheme}://{name}.{self.content_suffix}"

    def page_of(self, host: str) -> str | None:
        """The page name of a content host, or None."""
        host, end = host.lower().rstrip("."), "." + self.content_suffix
        name = host[: -len(end)] if host.endswith(end) else ""
        return name if NAME_RE.match(name) and name not in RESERVED_NAMES else None

    def sign_in(self, url: str) -> str:
        return f"{self.origin}/oauth2/start?rd={quote(url, safe='')}"


class Gateway:
    """Everything the request handler shares."""

    def __init__(
        self,
        store: Store,
        site: Site,
        identity: Identity,
        ttl: float = 5.0,
        cache_bytes: int = 256 * MB,
        file_bytes: int = 4 * MB,
    ):
        self.store, self.site, self.identity = store, site, identity
        self.files = FileCache(store, cache_bytes, file_bytes)
        self.pages = PageCache(store, self.files, ttl)
        self.assets = Assets(site.origin)
        self.limit = RateLimit()

    def facts(self, name: str, email: str) -> dict:
        """What the bar shows. Emails only for a signed-in viewer."""
        current, visibility, owner = self.pages.get(name)
        versions = []
        for version in reversed(self.pages.versions(name)):
            meta = self.files.meta(name, version)
            item = {
                "version": version,
                "published_at": meta.get("published_at", ""),
                "description": meta.get("description", ""),
            }
            if email:
                item["published_by"] = meta.get("published_by", "")
            versions.append(item)
        return {
            "name": name,
            "visibility": visibility,
            "current": current,
            "published_by": owner if email else "",
            "role": "owner" if email and email.lower() == owner.strip().lower() else "viewer",
            "viewer": email,
            "email_domain": self.site.email_domain,
            "content_origin": self.site.content_origin(name),
            "versions": versions,
        }


BADGE_CSS = """
.badge { font-size: .75rem; padding: .05rem .4rem; border-radius: .6rem; border: 1px solid; }
.private { color: #a33; } .ontic { color: #555; } .public { color: #276; }
"""


def listing_html(gw: Gateway, email: str) -> str:
    rows = []
    for name in gw.store.names():
        version, visibility, owner = gw.pages.get(name)
        if not version or not allowed(visibility, owner, email, gw.site.email_domain):
            continue
        meta = gw.files.meta(name, version)
        cells = [
            f'<a href="/{quote(name)}/">{short(name, NAME_CHARS)}</a>',
            f'<span class="badge {visibility}">{visibility}</span>',
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


def bad_path(rest: str) -> bool:
    return any(p in (".", "..") or "\\" in p for p in rest.split("/"))


def etag_matches(header: str | None, etag: str) -> bool:
    tags = [t.strip().removeprefix("W/") for t in (header or "").split(",")]
    return "*" in tags or etag in tags


def make_handler(gw: Gateway):
    site = gw.site

    class Handler(BaseHTTPRequestHandler):
        server_version = "ontic-pages"
        protocol_version = "HTTP/1.1"
        timeout = 120

        # --- who is asking ------------------------------------------------------------------

        def begin(self):
            self.who: str | None = None  # None: not asked yet
            self.cookies: list[str] = []
            self.on_apex = False

        def email(self, required: bool = True) -> str:
            """The signed-in email or "". If oauth2-proxy does not answer, raise, unless the
            answer only adds to a page anyone may open (required=False)."""
            if self.who is None:
                try:
                    self.who, self.cookies = gw.identity(self.headers.get("Cookie") or "")
                except IdentityUnavailable:
                    if required:
                        raise
                    return ""
            return self.who

        def may_open(self, name: str, visibility: str, owner: str, url: str, page=True) -> bool:
            """Answer and return False unless this viewer may open the page. Signed out, a page
            load goes to sign-in and anything else gets 401."""
            if visibility == "public":
                return True
            email = self.email()
            if allowed(visibility, owner, email, site.email_domain):
                return True
            if email:
                self.forbidden(name, visibility)
            elif page:
                self.redirect(site.sign_in(url), 302)
            else:
                self.send_text(401, f"sign in at {site.origin}/ first\n")
            return False

        def log_message(self, fmt, *args):
            who = getattr(self, "who", None) or "-"
            sys.stderr.write(f"{self.log_date_time_string()} {who} {fmt % args}\n")

        # --- answers ------------------------------------------------------------------------

        def end_headers(self):
            for cookie in getattr(self, "cookies", []):
                self.send_header("Set-Cookie", cookie)
            self.cookies = []
            super().end_headers()

        def send_body(self, code: int, body: bytes, headers: dict[str, str]):
            self.send_response(code)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def send_text(self, code: int, text: str, ctype="text/plain; charset=utf-8"):
            csp = PLAIN_CSP if self.on_apex else f"frame-ancestors 'self' {site.origin}"
            self.send_body(code, text.encode(), {
                "Content-Type": ctype,
                "Cache-Control": "no-cache",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": csp,
            })  # fmt: skip

        def send_html(self, code: int, text: str):
            self.send_text(code, text, "text/html; charset=utf-8")

        def send_json(self, code: int, value: dict):
            self.send_body(code, json.dumps(value).encode(), {
                "Content-Type": "application/json",
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            })  # fmt: skip

        def redirect(self, location: str, code: int = 301):
            self.send_body(code, b"", {"Location": location})

        def forbidden(self, name: str, visibility: str):
            who = "its publisher" if visibility == "private" else f"@{site.email_domain} accounts"
            self.send_html(
                403,
                f"<!doctype html><title>Not allowed</title><p>{html.escape(name)} is a "
                f"{visibility} page, open to {html.escape(who)} only.</p>\n",
            )

        def send_asset(self, data: bytes, ctype: str, immutable: bool):
            self.send_body(200, data, {
                "Content-Type": ctype,
                "Cache-Control": f"public, {YEAR}" if immutable else "no-cache",
                "X-Content-Type-Options": "nosniff",
            })  # fmt: skip

        # --- routing ------------------------------------------------------------------------

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            self.begin()
            url = urlsplit(self.path)
            path, query = unquote(url.path), url.query
            host = (self.headers.get("Host") or "").lower()
            try:
                if path == "/_health":
                    return self.send_text(200, "ok\n")
                if host == site.apex:
                    self.on_apex = True
                    return self.apex_get(path, query)
                name = site.page_of(host)
                if name:
                    return self.content_get(name, path, query)
                if path == "/_tls-ask":
                    return self.tls_ask(query)
                return self.send_text(404, f"unknown host; the pages are at {site.origin}/\n")
            except IdentityUnavailable as err:
                self.log_error("oauth2-proxy did not answer: %s", err)
                return self.send_text(503, "sign-in is not answering, try again\n")
            except ClientError as err:
                self.log_error("store error: %s", err)
                return self.send_text(502, "store error\n")

        def tls_ask(self, query: str):
            """Caddy asks before getting a certificate for a host: only existing pages."""
            domain = parse_qs(query).get("domain", [""])[0]
            name = site.page_of(domain)
            exists = bool(name and gw.pages.get(name)[0])
            return self.send_text(200 if exists else 404, "ok\n" if exists else "no such page\n")

        def apex_get(self, path: str, query: str):
            q = f"?{query}" if query else ""
            if path == "/":
                email = self.email()
                if not email:
                    return self.redirect(site.sign_in(f"{site.origin}/"), 302)
                return self.send_html(200, listing_html(gw, email))
            if found := gw.assets.lookup(path, content_host=False):
                return self.send_asset(*found)
            if m := API_PAGE.match(path):
                return self.api_get(m.group(1))
            if path.startswith("/public/"):
                return self.redirect(quote(path[len("/public") :]) + q)
            name, slash, rest = path[1:].partition("/")
            if not NAME_RE.match(name) or name in RESERVED_NAMES or bad_path(rest):
                return self.send_text(404, "not found\n")
            if not slash:
                return self.redirect(f"/{quote(name)}/{q}")
            version, visibility, owner = gw.pages.get(name)
            if not version:
                return self.send_text(404, f"no page named {name}\n")
            here = f"{site.origin}{quote(path)}{q}"
            if not self.may_open(name, visibility, owner, here):
                return
            if rest == "_info":
                if not self.email():  # metadata stays signed in, even for public pages
                    return self.redirect(site.sign_in(here), 302)
                page = info_html(name, *history(gw.store, name), visibility)
                return self.send_html(200, page)
            viewing = None
            if m := VERSIONED.match(rest):
                viewing = m.group(1)
                if viewing not in gw.pages.versions(name):
                    return self.send_text(404, f"{name} has no version {viewing}\n")
                if m.group(2) is None:
                    return self.redirect(f"/{quote(name)}/_v/{viewing}/{q}")
            self.send_shell(name, viewing, "/" + rest, query, here)

        def send_shell(self, name: str, viewing: str | None, path: str, query: str, here: str):
            page = gw.facts(name, self.email(required=False))
            src = site.content_origin(name) + quote(path) + (f"?{query}" if query else "")
            view = {
                "version": viewing,
                "path": path + (f"?{query}" if query else ""),
                "src": src,
                "raw": src + ("&" if query else "?") + "raw=1",
                "signin": site.sign_in(here),
            }
            self.send_body(200, shell_html(page, view, gw.assets).encode(), {
                "Content-Type": "text/html; charset=utf-8",
                "Cache-Control": "no-store",
                "Content-Security-Policy": shell_csp(f"{site.scheme}://*.{site.content_suffix}"),
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
            })  # fmt: skip

        # --- the JSON API (apex only) -------------------------------------------------------

        def api_page(self, name: str, required: bool):
            """(current, visibility, owner, email) after the access check, else None (answered)."""
            if not NAME_RE.match(name) or name in RESERVED_NAMES:
                return self.send_json(404, {"error": "no such page"})
            version, visibility, owner = gw.pages.get(name)
            if not version:
                return self.send_json(404, {"error": f"no page named {name}"})
            email = self.email(required=required or visibility != "public")
            if not allowed(visibility, owner, email, site.email_domain):
                code, error = (403, "not allowed") if email else (401, "sign in first")
                return self.send_json(code, {"error": error})
            return version, visibility, owner, email

        def api_get(self, name: str):
            if found := self.api_page(name, required=False):
                self.send_json(200, gw.facts(name, found[3]))

        def do_POST(self):
            self.begin()
            path = unquote(urlsplit(self.path).path)
            host = (self.headers.get("Host") or "").lower()
            self.on_apex = host == site.apex
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if not 0 <= length <= 4096:
                self.close_connection = True
                return self.send_json(413, {"error": "body too large"})
            body = self.rfile.read(length)
            m = API_VISIBILITY.match(path)
            if not self.on_apex or not m:
                return self.send_json(404 if self.on_apex else 405, {"error": "no writes here"})
            # A page's own scripts run on <name>.<suffix>, same-site with the apex, so the
            # browser sends the viewer's cookie with their requests too. Only the shell itself
            # passes these three checks.
            same = self.headers.get("Sec-Fetch-Site") == "same-origin"
            if not same or self.headers.get("Origin") != site.origin:
                return self.send_json(403, {"error": "writes only from the bar"})
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype != "application/json":
                return self.send_json(415, {"error": "send application/json"})
            try:
                found = self.api_page(m.group(1), required=True)
                if not found:
                    return
                _, _, owner, email = found
                if not email:
                    return self.send_json(401, {"error": "sign in first"})
                if not gw.limit.allow(email.lower()):
                    return self.send_json(429, {"error": "too many changes, wait a minute"})
                try:
                    level = json.loads(body).get("visibility")
                except (ValueError, AttributeError):
                    level = None
                if level not in VISIBILITIES:
                    return self.send_json(400, {"error": "visibility: private, ontic or public"})
                if email.strip().lower() != owner.strip().lower():
                    return self.send_json(403, {"error": "only the owner can change this"})
                gw.store.set_visibility(m.group(1), level)
                gw.pages.forget(m.group(1))
                self.send_json(200, gw.facts(m.group(1), email))
            except IdentityUnavailable:
                self.send_json(503, {"error": "sign-in is not answering, try again"})
            except ClientError as err:
                self.log_error("store error: %s", err)
                self.send_json(502, {"error": "store error"})

        # --- the content host ---------------------------------------------------------------

        def content_get(self, name: str, path: str, query: str):
            q = f"?{query}" if query else ""
            if found := gw.assets.lookup(path, content_host=True):
                return self.send_asset(*found)
            rest = path[1:]
            if bad_path(rest):
                return self.send_text(404, "not found\n")
            current, visibility, owner = gw.pages.get(name)
            if not current:
                return self.send_text(404, f"no page named {name}\n")
            version, base = current, "/"
            if m := VERSIONED.match(rest):
                version, base = m.group(1), f"/_v/{m.group(1)}/"
                if m.group(2) is None:
                    return self.redirect(f"{base}{q}")
                rest = m.group(2)[1:]
            dest = self.headers.get("Sec-Fetch-Dest", "")
            raw = parse_qs(query).get("raw") == ["1"]
            itself = self.headers.get("Sec-Fetch-Site") == "same-origin"
            if dest == "document" and not raw and not itself:
                return self.redirect(f"{site.origin}/{quote(name)}{quote(path)}{q}", 302)
            here = f"{site.content_origin(name)}{quote(path)}{q}"
            if not self.may_open(name, visibility, owner, here, page=dest in ("document", "")):
                return
            self.send_content(name, version, rest, base, q, visibility, dest == "iframe")

        def send_content(self, name, version, rest, base, q, visibility, frame):
            if rest == "" or rest.endswith("/"):
                rest += "index.html"
            public = visibility == "public"
            revalidate = "no-cache" if public else "private, no-cache"
            cache = f"{'public' if public else 'private'}, {YEAR}" if base != "/" else revalidate
            headers = {
                "Content-Type": content_type(rest),
                "Cache-Control": cache,
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": f"frame-ancestors 'self' {site.origin}",
            }
            key = gw.store.key(name, version, rest)
            if self.headers.get("Range"):
                try:
                    obj = gw.store.get(key, self.headers.get("Range"))
                except ClientError as err:
                    if err.response.get("Error", {}).get("Code") == "InvalidRange":
                        return self.send_text(416, "range not satisfiable\n")
                    raise
                if obj is None:
                    return self.send_text(404, "not found\n")
                return self.send_stream(obj, headers)
            found = gw.files.get(name, version, rest)
            if found is None:
                if not rest.endswith("index.html") and gw.store.exists(f"{key}/index.html"):
                    return self.redirect(f"{base}{quote(rest)}/{q}")
                return self.send_text(404, "not found\n")
            entry, body = found
            try:
                is_html = headers["Content-Type"].startswith("text/html")
                bridge = is_html and frame
                etag = entry.etag
                if bridge:  # rewritten HTML: its own ETag, and always revalidated
                    etag = f'{etag[:-1]}-b{gw.assets.bridge_hash}"'
                    headers["Cache-Control"] = revalidate
                headers["ETag"] = etag
                if is_html:
                    headers["Vary"] = "Sec-Fetch-Dest"
                if etag_matches(self.headers.get("If-None-Match"), etag):
                    self.send_response(304)
                    for k in ("ETag", "Cache-Control", "Vary"):
                        if k in headers:
                            self.send_header(k, headers[k])
                    return self.end_headers()
                data = entry.data
                if bridge and data is None:
                    body = body or gw.store.get(key)["Body"]
                    data = body.read()
                if bridge:
                    return self.send_body(200, inject(data, gw.assets.bridge_tag), headers)
                headers["Accept-Ranges"] = "bytes"
                if data is not None:
                    return self.send_body(200, data, headers)
                body = body or gw.store.get(key)["Body"]
                self.send_stream({"Body": body, "ContentLength": entry.size}, headers)
                body = None  # send_stream closed it
            finally:
                if body is not None:
                    body.close()

        def send_stream(self, obj: dict, headers: dict[str, str]):
            self.send_response(206 if obj.get("ContentRange") else 200)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(obj["ContentLength"]))
            if obj.get("ContentRange"):
                self.send_header("Content-Range", obj["ContentRange"])
            self.send_header("Accept-Ranges", "bytes")
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
    site: Site | None = None,
    identity: Identity | None = None,
    ttl: float = 5.0,
    local_email: str = "",
    auth_url: str = DEFAULT_AUTH_URL,
    cache_bytes: int = 256 * MB,
    file_bytes: int = 4 * MB,
) -> ThreadingHTTPServer:
    """identity: who sent a Cookie header; default: --local-as, else oauth2-proxy at auth_url."""
    if identity is None:
        identity = fixed(local_email) if local_email else OAuth2Proxy(auth_url, ttl=ttl)
    gw = Gateway(store, site or Site(), identity, ttl, cache_bytes, file_bytes)
    server = ThreadingHTTPServer((host, port), make_handler(gw))
    server.daemon_threads = True
    return server


def serve(store: Store, host: str, port: int, **kwargs) -> None:
    server = make_server(store, host, port, **kwargs)
    site = kwargs.get("site") or Site()
    print(f"serving {store.bucket}/{store.prefix} on http://{host}:{server.server_port}/")
    print(f"open {site.origin}/ (pages at {site.content_origin('<name>')}/)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
