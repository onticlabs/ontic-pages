import base64
import json

import pytest

from ontic_pages.tokens import LoginCodes, check_secret, sign, verify

SECRET = "s" * 40
NOW = 1_790_000_000
CODE = "c" * 43


def test_sign_and_verify():
    token = sign(SECRET, "a@onticlabs.io", now=NOW)
    prefix, claims, _ = token.split(".")
    assert prefix == "op1"
    body = json.loads(base64.urlsafe_b64decode(claims + "=" * (-len(claims) % 4)))
    assert body == {"sub": "a@onticlabs.io", "iat": NOW, "exp": NOW + 30 * 24 * 3600}
    assert verify(SECRET, token, now=NOW) == "a@onticlabs.io"
    assert verify(SECRET, token, now=NOW + 30 * 24 * 3600 - 1) == "a@onticlabs.io"


def test_expired_and_tampered_tokens():
    token = sign(SECRET, "a@onticlabs.io", now=NOW)
    assert verify(SECRET, token, now=NOW + 30 * 24 * 3600) is None  # expired
    assert verify(SECRET, token, now=NOW - 3600) is None  # issued in the future
    assert verify("t" * 40, token, now=NOW) is None  # another secret
    assert verify("", token, now=NOW) is None
    prefix, claims, sig = token.split(".")
    forged = (
        base64.urlsafe_b64encode(
            json.dumps({"sub": "boss@onticlabs.io", "iat": NOW, "exp": NOW + 99}).encode()
        )
        .decode()
        .rstrip("=")
    )
    for bad in (
        f"{prefix}.{forged}.{sig}",  # other claims, old signature
        f"op2.{claims}.{sig}",
        f"{prefix}.{claims}.{sig[:-2]}AA",
        f"{prefix}.{claims}",
        token + ".x",
        "",
        "garbage",
    ):
        assert verify(SECRET, bad, now=NOW) is None, bad
    # A well signed token must still carry sane claims.
    odd = sign(SECRET, "no-at-sign", now=NOW)
    assert verify(SECRET, odd, now=NOW) is None


def test_secret_length():
    with pytest.raises(SystemExit, match="openssl rand"):
        check_secret("short")
    assert check_secret(SECRET) == SECRET


def test_login_code_flow():
    codes = LoginCodes(seconds=300, cap=3)
    assert codes.claim(CODE, now=0) is None  # not shown yet
    assert not codes.approve(CODE, "a@onticlabs.io", now=0)  # never shown: no approving
    assert codes.open(CODE, now=0)
    assert codes.open(CODE, now=1)  # a reload shows it again
    assert codes.claim(CODE, now=2) is None  # not allowed yet
    assert codes.approve(CODE, "a@onticlabs.io", now=3)
    assert not codes.approve(CODE, "b@onticlabs.io", now=4)  # single use
    assert not codes.open(CODE, now=4)  # an approved code is not shown again
    assert codes.claim("d" * 43, now=5) is None  # wrong code
    assert codes.claim(CODE, now=5) == "a@onticlabs.io"
    assert codes.claim(CODE, now=6) is None  # handed out once
    assert not codes.open(CODE, now=7) and not codes.approve(CODE, "a@onticlabs.io", now=7)
    assert not codes.open("bad code!", now=7)  # not a code at all


def test_login_codes_expire_and_are_capped():
    codes = LoginCodes(seconds=300, cap=2)
    assert codes.open("a" * 43, now=0) and codes.open("b" * 43, now=10)
    assert not codes.open("e" * 43, now=20)  # full
    assert not codes.approve("a" * 43, "x@onticlabs.io", now=301)  # too old
    assert codes.open("e" * 43, now=301)  # the old one made room
    assert codes.approve("b" * 43, "x@onticlabs.io", now=305)
    assert codes.claim("b" * 43, now=311) is None  # approved, but claimed too late
