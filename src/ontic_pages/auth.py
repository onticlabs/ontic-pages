"""Who is asking, and may they: the oauth2-proxy subrequest, the access rule and a write limit.

The gateway never reads identity headers from the client. It asks oauth2-proxy's /oauth2/auth
with only the request's Cookie header: 202 plus X-Auth-Request-Email means signed in, anything
else means anonymous, and no answer raises IdentityUnavailable (the request cannot be decided).
"""

from __future__ import annotations

import hashlib
import http.client
import threading
import time
from collections import deque
from collections.abc import Callable
from urllib.parse import urlsplit

DEFAULT_AUTH_URL = "http://127.0.0.1:4190/oauth2/auth"

# Cookie header -> (email or "", Set-Cookie headers to pass on to the browser).
Identity = Callable[[str], tuple[str, list[str]]]


class IdentityUnavailable(Exception):
    """oauth2-proxy did not answer."""


def allowed(visibility: str, owner: str, email: str, domain: str) -> bool:
    """public: anyone. ontic: an email at the domain. private: the current version's publisher."""
    email = email.strip().lower()
    if visibility == "public":
        return True
    if visibility == "private":
        return bool(email) and email == owner.strip().lower()
    return bool(email) and (not domain or email.endswith("@" + domain.lower()))


def fixed(email: str) -> Identity:
    """--local-as: everyone is EMAIL, no oauth2-proxy."""
    return lambda cookie: (email, [])


class OAuth2Proxy:
    """Ask oauth2-proxy who the cookie belongs to, and remember the answer for `ttl` seconds per
    cookie so a page with many files costs one subrequest. A refreshed session comes back as
    Set-Cookie, which the gateway passes on (only on the answer that asked)."""

    def __init__(self, auth_url: str = DEFAULT_AUTH_URL, ttl: float = 5.0, timeout: float = 3.0):
        url = urlsplit(auth_url)
        if url.scheme != "http" or not url.hostname:
            raise SystemExit(f"--auth-url must be a plain http URL, got {auth_url!r}")
        self.host, self.port = url.hostname, url.port or 80
        self.path = (url.path or "/") + (f"?{url.query}" if url.query else "")
        self.ttl, self.timeout = ttl, timeout
        self.lock = threading.Lock()
        self.seen: dict[str, tuple[float, str]] = {}

    def __call__(self, cookie: str) -> tuple[str, list[str]]:
        if not cookie:
            return "", []
        key = hashlib.sha256(cookie.encode()).hexdigest()
        now = time.monotonic()
        with self.lock:
            hit = self.seen.get(key)
        if hit and now - hit[0] < self.ttl:
            return hit[1], []
        conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        try:
            conn.request("GET", self.path, headers={"Cookie": cookie, "Accept": "*/*"})
            resp = conn.getresponse()
            resp.read()
        except (OSError, http.client.HTTPException) as err:
            raise IdentityUnavailable(str(err)) from err
        finally:
            conn.close()
        email = (resp.getheader("X-Auth-Request-Email") or "").strip() if resp.status == 202 else ""
        with self.lock:
            if len(self.seen) > 10_000:
                self.seen.clear()
            self.seen[key] = (now, email)
        return email, resp.headers.get_all("Set-Cookie") or []


class RateLimit:
    """At most `count` writes per `seconds` per identity."""

    def __init__(self, count: int = 20, seconds: float = 60.0):
        self.count, self.seconds = count, seconds
        self.lock = threading.Lock()
        self.hits: dict[str, deque] = {}

    def allow(self, who: str) -> bool:
        now = time.monotonic()
        with self.lock:
            hits = self.hits.setdefault(who, deque())
            while hits and now - hits[0] > self.seconds:
                hits.popleft()
            if len(hits) >= self.count:
                return False
            hits.append(now)
            return True
