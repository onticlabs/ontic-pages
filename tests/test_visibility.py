import threading
from datetime import UTC, datetime

import pytest
from test_gateway import get

from ontic_pages.cli import main
from ontic_pages.gateway import make_server
from ontic_pages.publish import publish
from ontic_pages.store import Store

T1 = datetime(2026, 10, 7, 15, 30, tzinfo=UTC)
OWNER = {"X-Forwarded-Email": "owner@onticlabs.io"}
OTHER = {"X-Forwarded-Email": "other@onticlabs.io"}
OUTSIDER = {"X-Forwarded-Email": "someone@gmail.com"}


def test_visibility_file_and_default(store, s3, site):
    publish(store, site, "report", now=T1)
    assert store.visibility("report") == "ontic"
    assert ("test-bucket", "pages/report/visibility") not in s3.objects
    store.set_visibility("report", "public")
    assert s3.objects[("test-bucket", "pages/report/visibility")][0] == b"public"
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
    store = Store(cli_env, "test-bucket", "pages/")
    assert store.meta("report", store.current("report"))["published_by"] == "owner@onticlabs.io"

    main(["share", "report", "public"])
    out = capsys.readouterr().out
    assert "report is now public" in out and "https://pages.example.org/public/report/" in out
    main(["url", "report"])
    assert capsys.readouterr().out.strip() == "https://pages.example.org/public/report/"

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
def pages(store, site):
    """One page per level, all published by owner@onticlabs.io."""
    for name, level in (("pub", "public"), ("team", "ontic"), ("mine", "private")):
        publish(store, site, name, f"{level} page", visibility=level,
                published_by="owner@onticlabs.io", now=T1)  # fmt: skip
    srv = make_server(store, "127.0.0.1", 0, ttl=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def test_public_page(pages):
    # Caddy sends /public/* without oauth2-proxy: no email at all.
    assert get(pages, "/public/pub/", who=None)[::2] == (200, b"<h1>version one</h1>")
    assert get(pages, "/public/pub/style.css", who=None)[0] == 200
    status, headers, _ = get(pages, "/public/pub", who=None)
    assert (status, headers["Location"]) == (301, "/public/pub/")
    # The signed-in path works for public pages too.
    assert get(pages, "/pub/", who=OUTSIDER)[0] == 200
    # Metadata stays behind sign-in.
    status, headers, _ = get(pages, "/public/pub/_info", who=None)
    assert (status, headers["Location"]) == (302, "/pub/_info")


def test_public_path_redirects_other_levels(pages):
    for name in ("team", "mine"):
        status, headers, _ = get(pages, f"/public/{name}/img/dot.png?x=1", who=None)
        assert (status, headers["Location"]) == (302, f"/{name}/img/dot.png?x=1")
    assert get(pages, "/public/ghost/", who=None)[0] == 404
    assert get(pages, "/public/%2e%2e/team/", who=None)[0] == 404


def test_ontic_page(pages):
    status, _, body = get(pages, "/team/", who=None)
    assert status == 403 and b"ontic page" in body
    assert get(pages, "/team/", who=OUTSIDER)[0] == 403
    assert get(pages, "/team/", who={"X-Forwarded-Email": " "})[0] == 403
    assert get(pages, "/team/", who=OTHER)[0] == 200
    assert get(pages, "/team/_info", who=OTHER)[0] == 200


def test_private_page(pages):
    assert get(pages, "/mine/", who=OWNER)[0] == 200
    assert get(pages, "/mine/", who={"X-Forwarded-Email": "Owner@OnticLabs.io"})[0] == 200
    status, _, body = get(pages, "/mine/", who=OTHER)
    assert status == 403 and b"private page" in body
    assert get(pages, "/mine/_info", who=OTHER)[0] == 403
    assert get(pages, "/mine/", who=None)[0] == 403


def test_listing_hides_private_and_shows_badges(pages):
    owner = get(pages, "/", who=OWNER)[2].decode()
    other = get(pages, "/", who=OTHER)[2].decode()
    for name in ("pub", "team", "mine"):
        assert f'<a href="/{name}/">' in owner
    assert '<a href="/mine/">' not in other and '<a href="/team/">' in other
    assert '<span class="badge public">public</span>' in other
    assert '<a href="/public/pub/">public link</a>' in other
    assert '<span class="badge ontic">ontic</span>' in other
    assert '<span class="badge private">private</span>' in owner
    assert "/public/team/" not in other


def test_listing_shortens_long_names(store, site):
    name = "a-really-long-page-name-that-goes-past-the-limit"
    publish(store, site, name, "d" * 100, now=T1)
    srv = make_server(store, "127.0.0.1", 0, ttl=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        text = get(srv, "/")[2].decode()
    finally:
        srv.shutdown()
        srv.server_close()
    assert f'<span title="{name}">{name[:31]}…</span>' in text
    assert f'<span title="{"d" * 100}">{"d" * 59}…</span>' in text


def test_local_as(store, site, cli_env):
    publish(store, site, "mine", visibility="private", published_by="owner@onticlabs.io")
    srv = make_server(store, "127.0.0.1", 0, ttl=0, local_email="owner@onticlabs.io")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        assert get(srv, "/mine/", who=None)[0] == 200
        assert get(srv, "/mine/", who=OTHER)[0] == 403  # a sent header still wins
    finally:
        srv.shutdown()
        srv.server_close()
    with pytest.raises(SystemExit, match="loopback|this machine"):
        main(["gateway", "--host", "0.0.0.0", "--local-as", "owner@onticlabs.io"])
