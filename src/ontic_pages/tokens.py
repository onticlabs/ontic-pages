"""Sign-in for the command line: signed tokens and the browser hand-off that hands them out.

A token is `op1.<claims>.<signature>`: the claims {sub: email, iat, exp} as base64url JSON, and an
HMAC-SHA256 of `op1.<claims>` with the gateway's secret (ONTIC_PAGES_TOKEN_SECRET). Nothing about
a token is stored; changing the secret ends every token.

`ontic-pages login` makes a random code, opens <apex>/_cli/login?code=<code> in the browser and
asks the gateway for the token of that code every two seconds. The page (signed in through
oauth2-proxy like every apex page) remembers the code; Allow approves it for the signed-in email;
the next poll gets the token, once; the code is then used up. Codes live in memory only, at most
MAX_CODES at a time, for CODE_SECONDS from when the page first showed them.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import threading
import time

PREFIX = "op1"
TOKEN_SECONDS = 30 * 24 * 3600
CODE_SECONDS = 300
MAX_CODES = 100
MIN_SECRET = 32
CODE_RE = re.compile(r"^[A-Za-z0-9_-]{20,128}$")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _mac(secret: str, signed: str) -> str:
    return _b64(hmac.new(secret.encode(), signed.encode(), hashlib.sha256).digest())


def check_secret(secret: str) -> str:
    if len(secret) < MIN_SECRET:
        raise SystemExit(
            f"ONTIC_PAGES_TOKEN_SECRET is too short (at least {MIN_SECRET} characters; "
            "make one with: openssl rand -base64 32)"
        )
    return secret


def sign(secret: str, email: str, now: float | None = None, seconds: int = TOKEN_SECONDS) -> str:
    now = int(time.time() if now is None else now)
    claims = _b64(json.dumps({"sub": email, "iat": now, "exp": now + seconds}).encode())
    signed = f"{PREFIX}.{claims}"
    return f"{signed}.{_mac(secret, signed)}"


def verify(secret: str, token: str, now: float | None = None) -> str | None:
    """The email of a well signed, unexpired token, else None."""
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != PREFIX or not secret:
        return None
    if not hmac.compare_digest(_mac(secret, f"{parts[0]}.{parts[1]}"), parts[2]):
        return None
    try:
        claims = json.loads(_unb64(parts[1]))
        sub, iat, exp = claims["sub"], claims["iat"], claims["exp"]
    except (ValueError, TypeError, KeyError):
        return None
    now = time.time() if now is None else now
    ok = isinstance(sub, str) and "@" in sub and isinstance(exp, int) and isinstance(iat, int)
    return sub if ok and iat <= now + 60 and now < exp else None


USED = "\0used"


class LoginCodes:
    """Codes from `ontic-pages login`, from when the login page first showed them until they
    expire. code -> (first seen, "" or the approved email or USED once the token went out)."""

    def __init__(self, seconds: float = CODE_SECONDS, cap: int = MAX_CODES):
        self.seconds, self.cap = seconds, cap
        self.lock = threading.Lock()
        self.codes: dict[str, tuple[float, str]] = {}

    def _prune(self, now: float) -> None:
        for code in [c for c, (seen, _) in self.codes.items() if now - seen > self.seconds]:
            del self.codes[code]

    def open(self, code: str, now: float | None = None) -> bool:
        """The login page shows the code: remember it. False when it cannot be used (bad, used
        up, too old, or too many waiting)."""
        now = time.monotonic() if now is None else now
        if not CODE_RE.match(code):
            return False
        with self.lock:
            self._prune(now)
            if code in self.codes:
                return not self.codes[code][1]  # shown again, unless approved or used
            if len(self.codes) >= self.cap:
                return False
            self.codes[code] = (now, "")
            return True

    def approve(self, code: str, email: str, now: float | None = None) -> bool:
        """Allow: the code's token is for `email`. Only for a shown, unapproved, fresh code."""
        now = time.monotonic() if now is None else now
        with self.lock:
            self._prune(now)
            entry = self.codes.get(code)
            if not entry or entry[1] or not email:
                return False
            self.codes[code] = (entry[0], email)
            return True

    def claim(self, code: str, now: float | None = None) -> str | None:
        """The approved email, once; then the code is used up. None while not approved."""
        now = time.monotonic() if now is None else now
        with self.lock:
            self._prune(now)
            entry = self.codes.get(code)
            if not entry or entry[1] in ("", USED):
                return None
            self.codes[code] = (entry[0], USED)
            return entry[1]
