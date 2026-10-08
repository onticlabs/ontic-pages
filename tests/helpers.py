"""Start a gateway on a free port and talk to it as a browser would, by Host header."""

from __future__ import annotations

import http.client
import threading

from ontic_pages.gateway import Site, make_server

APEX = "pages.test"
ORIGIN = f"https://{APEX}"
SITE = Site(ORIGIN, email_domain="onticlabs.io")
TEAM = "tester@onticlabs.io"


def cookie_identity(cookie: str) -> tuple[str, list[str]]:
    """Stands in for oauth2-proxy: the cookie `who=<email>` is signed in as <email>."""
    for part in cookie.split(";"):
        key, _, value = part.strip().partition("=")
        if key == "who":
            return value, []
    return "", []


def start(store, **kwargs):
    kwargs.setdefault("site", SITE)
    kwargs.setdefault("identity", cookie_identity)
    kwargs.setdefault("ttl", 0)
    srv = make_server(store, "127.0.0.1", 0, **kwargs)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def stop(srv) -> None:
    srv.shutdown()
    srv.server_close()


def request(srv, path, host=APEX, who=TEAM, headers=None, method="GET", body=None):
    """(status, headers, body). `who` signs in by cookie (None: signed out)."""
    sent = {"Host": host, **({"Cookie": f"who={who}"} if who else {}), **(headers or {})}
    conn = http.client.HTTPConnection("127.0.0.1", srv.server_port, timeout=5)
    conn.request(method, path, body=body, headers=sent)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, dict(resp.getheaders()), data


def content(srv, name, path, **kwargs):
    """A request to the page's own host, <name>.pages.test."""
    return request(srv, path, host=f"{name}.{APEX}", **kwargs)


FRAME = {"Sec-Fetch-Dest": "iframe", "Sec-Fetch-Site": "same-site"}
DOCUMENT = {"Sec-Fetch-Dest": "document", "Sec-Fetch-Site": "none"}
