from datetime import UTC, datetime
from urllib.parse import quote

import pytest
from helpers import DOCUMENT, FRAME, ORIGIN, content, request

from ontic_pages.cli import main
from ontic_pages.publish import publish
from ontic_pages.store import Store

T1 = datetime(2026, 10, 7, 15, 30, tzinfo=UTC)
OWNER = "owner@onticlabs.io"
OTHER = "other@onticlabs.io"
OUTSIDER = "someone@gmail.com"


def test_visibility_file_and_default(store, s3, site):
    publish(store, site, "report", now=T1)
    assert store.visibility("report") == "ontic"
    assert ("test-bucket", "report/visibility") not in s3.objects
    store.set_visibility("report", "public")
    assert s3.objects[("test-bucket", "report/visibility")][0] == b"public"
    assert store.visibility("report") == "public"
    store.put(store.key("report", "visibility"), b"garbage")
    assert store.visibility("report") == "private"  # unreadable fails closed
    with pytest.raises(ValueError, match="visibility must be"):
        store.set_visibility("report", "team")
    with pytest.raises(ValueError, match="bad page name"):
        publish(store, site, "public")


def test_publish_visibility_is_kept(store, site):
    publish(store, site, "report", visibility="private", now=T1)
    assert store.visibility("report") == "private"
    publish(store, site, "report")  # no flag: the level stays
    assert store.visibility("report") == "private"
    publish(store, site, "report", visibility="public")
    assert store.visibility("report") == "public"


def test_cli_share_url_list(cli_env, site, capsys, monkeypatch):
    monkeypatch.setenv("ONTIC_PAGES_EMAIL", "owner@onticlabs.io")
    main(["publish", str(site), "--name", "report", "--visibility", "private"])
    out = capsys.readouterr().out
    assert "private: only owner@onticlabs.io can open it" in out
    assert out.strip().endswith("https://pages.example.org/report/")
    store = Store(cli_env, "test-bucket")
    assert store.meta("report", store.current("report"))["published_by"] == "owner@onticlabs.io"

    main(["share", "report", "public"])
    out = capsys.readouterr().out
    assert "report is now public" in out and "https://pages.example.org/report/" in out
    main(["url", "report"])
    assert capsys.readouterr().out.strip() == "https://pages.example.org/report/"

    main(["share", "report", "ontic"])
    capsys.readouterr()
    main(["url", "report"])
    assert capsys.readouterr().out.strip() == "https://pages.example.org/report/"
    main(["list"])
    assert "report" in (line := capsys.readouterr().out) and " ontic " in line
    main(["list", "--name", "report"])
    assert capsys.readouterr().out.startswith("visibility: ontic")

    with pytest.raises(SystemExit, match="no page named"):
        main(["share", "ghost", "public"])
    with pytest.raises(SystemExit):
        main(["share", "report", "team"])


@pytest.fixture
def pages(store, site, serve):
    """One page per level, all published by owner@onticlabs.io."""
    for name, level in (("pub", "public"), ("team", "ontic"), ("mine", "private")):
        publish(store, site, name, f"{level} page", visibility=level,
                published_by=OWNER, now=T1)  # fmt: skip
    return serve()


def sign_in(url: str) -> str:
    return f"{ORIGIN}/oauth2/start?rd={quote(url, safe='')}"


def opens(server, name, who) -> tuple[int, int, int]:
    """Status of the shell, of the page in the frame, and of a file asked for directly."""
    return (
        request(server, f"/{name}/", who=who)[0],
        content(server, name, "/", who=who, headers=FRAME)[0],
        content(server, name, "/style.css", who=who)[0],
    )


def test_public_page(pages):
    for who in (None, OUTSIDER, OTHER):
        assert opens(pages, "pub", who) == (200, 200, 200)
    assert content(pages, "pub", "/?raw=1", who=None, headers=DOCUMENT)[0] == 200
    # Old /public/ links still work.
    status, headers, _ = request(pages, "/public/pub", who=None)
    assert (status, headers["Location"]) == (301, "/pub")
    # Metadata stays behind sign-in.
    status, headers, _ = request(pages, "/pub/_info", who=None)
    assert (status, headers["Location"]) == (302, sign_in(f"{ORIGIN}/pub/_info"))
    assert request(pages, "/pub/_info", who=OUTSIDER)[0] == 200


def test_ontic_page(pages):
    status, headers, _ = request(pages, "/team/docs/?a=1", who=None)
    assert (status, headers["Location"]) == (302, sign_in(f"{ORIGIN}/team/docs/?a=1"))
    assert content(pages, "team", "/", who=None, headers=FRAME)[0] == 401
    # Opened without the bar and signed out: sign in, then back to that address.
    status, headers, _ = content(pages, "team", "/?raw=1", who=None, headers=DOCUMENT)
    assert (status, headers["Location"]) == (302, sign_in("https://team.pages.test/?raw=1"))
    assert opens(pages, "team", OUTSIDER) == (403, 403, 403)
    assert opens(pages, "team", OTHER) == (200, 200, 200)
    assert request(pages, "/team/_info", who=OTHER)[0] == 200
    status, _, body = request(pages, "/team/", who=OUTSIDER)
    assert status == 403 and b"ontic page" in body


def test_private_page(pages):
    assert opens(pages, "mine", OWNER) == (200, 200, 200)
    assert opens(pages, "mine", "Owner@OnticLabs.io") == (200, 200, 200)
    assert opens(pages, "mine", OTHER) == (403, 403, 403)
    assert request(pages, "/mine/_info", who=OTHER)[0] == 403
    assert request(pages, "/mine/", who=None)[0] == 302
    status, _, body = request(pages, "/mine/", who=OTHER)
    assert status == 403 and b"private page" in body
    # Access is checked before a 304 too.
    match = {"If-None-Match": content(pages, "mine", "/style.css", who=OWNER)[1]["ETag"]}
    assert content(pages, "mine", "/style.css", who=OWNER, headers=match)[0] == 304
    assert content(pages, "mine", "/style.css", who=OTHER, headers=match)[0] == 403
    assert content(pages, "mine", "/style.css", who=None, headers=match)[0] == 302


def test_identity_headers_are_ignored(pages):
    forged = {"X-Forwarded-Email": OWNER, "X-Auth-Request-Email": OWNER}
    assert request(pages, "/mine/", who=None, headers=forged)[0] == 302
    assert content(pages, "mine", "/", who=OTHER, headers={**forged, **FRAME})[0] == 403


def test_listing_hides_private_and_shows_badges(pages):
    owner = request(pages, "/", who=OWNER)[2].decode()
    other = request(pages, "/", who=OTHER)[2].decode()
    for name in ("pub", "team", "mine"):
        assert f'<a href="/{name}/">' in owner
    assert '<a href="/mine/">' not in other and '<a href="/team/">' in other
    assert '<span class="badge public">public</span>' in other
    assert '<span class="badge ontic">ontic</span>' in other
    assert '<span class="badge private">private</span>' in owner


def test_listing_shortens_long_names(store, site, serve):
    name = "a-really-long-page-name-that-goes-past-the-limit"
    publish(store, site, name, "d" * 100, now=T1)
    text = request(serve(), "/")[2].decode()
    assert f'<span title="{name}">{name[:31]}…</span>' in text
    assert f'<span title="{"d" * 100}">{"d" * 59}…</span>' in text


def test_local_as(store, site, serve, cli_env):
    publish(store, site, "mine", visibility="private", published_by=OWNER)
    srv = serve(identity=None, local_email=OWNER)
    assert request(srv, "/mine/", who=None)[0] == 200
    assert request(srv, "/mine/", who=OTHER)[0] == 200  # cookies do not matter locally
    with pytest.raises(SystemExit, match="loopback|this machine"):
        main(["gateway", "--host", "0.0.0.0", "--local-as", OWNER])
