import http.client
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from helpers import FRAME, content, request

from ontic_pages.auth import IdentityUnavailable, OAuth2Proxy, RateLimit, allowed
from ontic_pages.publish import publish

T1 = datetime(2026, 10, 7, 15, 30, tzinfo=UTC)
GOOD = "_oauth2_proxy=good; other=1"


@pytest.fixture
def proxy():
    """A stand-in for oauth2-proxy's /oauth2/auth: the cookie _oauth2_proxy=good is
    tester@onticlabs.io (and its session is refreshed), anything else is 401."""
    seen = []

    class Auth(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append((self.path, dict(self.headers)))
            good = "_oauth2_proxy=good" in (self.headers.get("Cookie") or "")
            self.send_response(202 if good else 401)
            if good:
                self.send_header("X-Auth-Request-Email", "tester@onticlabs.io")
                self.send_header("Set-Cookie", "_oauth2_proxy=fresh; Domain=.pages.test")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Auth)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    srv.seen = seen
    srv.url = f"http://127.0.0.1:{srv.server_port}/oauth2/auth"
    yield srv
    srv.shutdown()
    srv.server_close()


def test_asks_oauth2_proxy_with_the_cookie_only(proxy):
    identity = OAuth2Proxy(proxy.url, ttl=60)
    assert identity("") == ("", []) and proxy.seen == []  # no cookie, no question
    assert identity(GOOD) == ("tester@onticlabs.io", ["_oauth2_proxy=fresh; Domain=.pages.test"])
    path, headers = proxy.seen[0]
    assert path == "/oauth2/auth" and headers["Cookie"] == GOOD
    assert not any(k.lower().startswith("x-") for k in headers)
    # Remembered per cookie: no second question, and the refreshed cookie went out once.
    assert identity(GOOD) == ("tester@onticlabs.io", []) and len(proxy.seen) == 1
    assert identity("_oauth2_proxy=bad") == ("", [])
    assert len(proxy.seen) == 2


def test_no_answer_raises():
    with pytest.raises(IdentityUnavailable):
        OAuth2Proxy("http://127.0.0.1:9/oauth2/auth", timeout=1)("_oauth2_proxy=x")
    with pytest.raises(SystemExit, match="plain http"):
        OAuth2Proxy("https://example.com/oauth2/auth")


def test_gateway_uses_oauth2_proxy(proxy, store, site, serve):
    publish(store, site, "team", visibility="ontic", now=T1)
    publish(store, site, "pub", visibility="public", now=T1)
    srv = serve(identity=None, auth_url=proxy.url)

    def get(path, cookie=None, name=None, **headers):
        sent = {**({"Cookie": cookie} if cookie else {}), **headers}
        if name:
            return content(srv, name, path, who=None, headers=sent)
        return request(srv, path, who=None, headers=sent)

    status, headers, _ = get("/team/", GOOD)
    assert status == 200 and headers["Set-Cookie"] == "_oauth2_proxy=fresh; Domain=.pages.test"
    assert get("/", name="team", cookie=GOOD, **FRAME)[0] == 200
    assert get("/team/", "_oauth2_proxy=bad")[0] == 302
    # A forged identity header is never read.
    assert get("/team/", None, **{"X-Forwarded-Email": "tester@onticlabs.io"})[0] == 302
    # Public pages need no question at all.
    before = len(proxy.seen)
    assert get("/", name="pub", **FRAME)[0] == 200
    assert len(proxy.seen) == before


def test_gateway_when_oauth2_proxy_is_down(store, site, serve):
    publish(store, site, "team", visibility="ontic", now=T1)
    publish(store, site, "pub", visibility="public", now=T1)
    srv = serve(identity=None, auth_url="http://127.0.0.1:9/oauth2/auth")
    assert request(srv, "/team/", who=None, headers={"Cookie": "a=b"})[0] == 503
    assert request(srv, "/pub/", who=None, headers={"Cookie": "a=b"})[0] == 200
    assert content(srv, "pub", "/", who=None, headers={"Cookie": "a=b"})[0] == 200


def test_rate_limit():
    limit = RateLimit(count=2, seconds=60)
    assert limit.allow("a") and limit.allow("a") and not limit.allow("a")
    assert limit.allow("b")
    limit.seconds = 0
    assert limit.allow("a")


def test_allowed():
    rules = [
        ("public", "", "", True),
        ("ontic", "", "", False),
        ("ontic", "", "x@onticlabs.io", True),
        ("ontic", "", "x@gmail.com", False),
        ("ontic", "", "x@evil-onticlabs.io", False),
        ("private", "o@onticlabs.io", "O@onticlabs.io ", True),
        ("private", "o@onticlabs.io", "x@onticlabs.io", False),
        ("private", "", "", False),
    ]
    for visibility, owner, email, expected in rules:
        assert allowed(visibility, owner, email, "onticlabs.io") is expected


def test_keep_alive(serve, store, site):
    """Several requests on one connection (HTTP/1.1), as Caddy and browsers send them."""
    publish(store, site, "pub", visibility="public", now=T1)
    srv = serve()
    conn = http.client.HTTPConnection("127.0.0.1", srv.server_port, timeout=5)
    for path in ("/", "/style.css", "/missing", "/"):
        conn.request("GET", path, headers={"Host": "pub.pages.test"})
        resp = conn.getresponse()
        resp.read()
        assert resp.status in (200, 404)
    conn.close()
