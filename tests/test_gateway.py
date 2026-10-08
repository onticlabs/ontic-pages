import http.client
import threading
from datetime import UTC, datetime

import pytest

from ontic_pages.gateway import make_server
from ontic_pages.publish import publish
from ontic_pages.store import content_type

T1 = datetime(2026, 10, 7, 15, 30, tzinfo=UTC)
T2 = datetime(2026, 10, 8, 9, 0, tzinfo=UTC)


@pytest.fixture
def server(store):
    srv = make_server(store, "127.0.0.1", 0, ttl=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


TEAM = {"X-Forwarded-Email": "tester@onticlabs.io"}


def get(server, path, headers=None, method="GET", who=TEAM):
    """A request as oauth2-proxy forwards it (signed in as tester@onticlabs.io by default)."""
    conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    conn.request(method, path, headers={**(who or {}), **(headers or {})})
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    return resp.status, dict(resp.getheaders()), body


def test_serves_current_and_switches(server, store, site):
    first = publish(store, site, "report", "first <b>bold</b>", now=T1)["version"]
    status, headers, body = get(server, "/report/")
    assert (status, body) == (200, b"<h1>version one</h1>")
    assert headers["Content-Type"] == "text/html; charset=utf-8"

    (site / "index.html").write_text("<h1>version two</h1>")
    publish(store, site, "report", "second", now=T2)
    assert get(server, "/report/")[2] == b"<h1>version two</h1>"

    store.set_current("report", first)
    assert get(server, "/report/")[2] == b"<h1>version one</h1>"
    assert get(server, "/report/index.html")[2] == b"<h1>version one</h1>"


def test_content_types(server, store, site):
    publish(store, site, "report", now=T1)
    expected = {
        "/report/style.css": "text/css; charset=utf-8",
        "/report/app.js": "text/javascript; charset=utf-8",
        "/report/data.json": "application/json; charset=utf-8",
        "/report/img/dot.png": "image/png",
        "/report/docs/": "text/html; charset=utf-8",
    }
    for path, ctype in expected.items():
        status, headers, _ = get(server, path)
        assert (status, headers["Content-Type"]) == (200, ctype), path
    assert content_type("x/model.glb") == "model/gltf-binary"
    assert content_type("x/README") == "application/octet-stream"


def test_redirects_and_404s(server, store, site):
    publish(store, site, "report", now=T1)
    status, headers, _ = get(server, "/report?x=1")
    assert (status, headers["Location"]) == (301, "/report/?x=1")
    status, headers, _ = get(server, "/report/docs")
    assert (status, headers["Location"]) == (301, "/report/docs/")
    assert get(server, "/report/missing.png")[0] == 404
    assert get(server, "/nope/")[0] == 404
    assert get(server, "/report/.DS_Store")[0] == 404
    assert get(server, "/report/../other/")[0] == 404
    assert get(server, "/report/%2e%2e/x")[0] == 404
    assert get(server, "/Bad_Name/")[0] == 404
    assert get(server, "/_health")[:3:2] == (200, b"ok\n")


def test_listing(server, store, site):
    assert b"No pages yet" in get(server, "/")[2]
    publish(store, site, "report", "first <b>bold</b>", now=T1)
    publish(store, site, "zeta", "another one", now=T2)
    status, headers, body = get(server, "/")
    assert status == 200 and headers["Content-Type"] == "text/html; charset=utf-8"
    text = body.decode()
    assert '<a href="/report/"><span title="report">report</span></a>' in text
    assert "first &lt;b&gt;bold&lt;/b&gt;" in text
    assert "2026-10-07 15:30" in text and "another one" in text


def test_range_and_head(server, store, site):
    publish(store, site, "report", now=T1)
    status, headers, body = get(server, "/report/img/dot.png", {"Range": "bytes=8-11"})
    assert (status, body) == (206, b"0123")
    assert headers["Content-Range"] == "bytes 8-11/18"
    assert get(server, "/report/img/dot.png", {"Range": "bytes=99-"})[0] == 416
    status, headers, body = get(server, "/report/style.css", method="HEAD")
    assert (status, body, headers["Content-Length"]) == (200, b"", "17")


def test_current_is_cached(store, site, s3):
    from ontic_pages.gateway import PageCache

    publish(store, site, "report", now=T1)
    cache = PageCache(store, ttl=60)
    s3.calls.clear()
    assert cache.get("report") == cache.get("report") == ("20261007T153000Z", "ontic", "")
    assert s3.calls == ["get_object", "get_object"]  # current and visibility, once
