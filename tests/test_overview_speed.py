"""The overview's cost: no page reads for its HTML, one listing, page states read in parallel,
the caches that keep it cheap (gateway.Gateway.openable, cache.NameCache, LabelCache), and the
overview as it comes: a loading screen, then each report once read (?stream=1)."""

import http.client
import json
import threading
from datetime import UTC, datetime

from botocore.exceptions import ClientError
from helpers import request
from test_research import OTHER, OWNER, call, host

from ontic_pages.cache import LabelCache, NameCache
from ontic_pages.publish import publish

T1 = datetime(2026, 10, 7, 15, 30, tzinfo=UTC)


def counting(store, monkeypatch, method):
    calls = []
    real = getattr(store, method)

    def counted(*args):
        calls.append(args)
        return real(*args)

    monkeypatch.setattr(store, method, counted)
    return calls


def test_overview_html_reads_no_page(local, store, site, monkeypatch):
    publish(store, site, "report", published_by=OWNER, now=T1)
    srv = local()
    names, currents = counting(store, monkeypatch, "names"), counting(store, monkeypatch, "current")
    text = request(srv, "/", host=host(srv), who=OWNER)[2].decode()
    assert '<a href="/?plain=1">The plain list of pages</a>' in text
    assert (names, currents) == ([], [])
    assert "/report/" in request(srv, "/?plain=1", host=host(srv), who=OWNER)[2].decode()


def test_overview_lists_the_bucket_once(local, store, site, monkeypatch):
    publish(store, site, "report", published_by=OWNER, now=T1)
    publish(store, site, "gone", published_by=OWNER, now=T1)
    srv = local()
    assert call(srv, "/_api/pages/gone/delete", body={"deleted": True}, who=OWNER)[0] == 200
    names = counting(store, monkeypatch, "names")
    data = call(srv, "/_api/overview", who=OWNER)[1]
    assert [r["name"] for r in data["reports"]] == ["report"]
    assert [r["name"] for r in data["deleted"]] == ["gone"]
    assert len(names) == 1


def test_page_states_are_read_in_parallel(local, store, site, monkeypatch):
    for name in ("a", "b", "c", "d"):
        publish(store, site, name, published_by=OWNER, now=T1)
    srv = local()
    both = threading.Barrier(2, timeout=5)  # passes only when two reads run at once
    real = store.current

    def current(name):
        if name in ("a", "b"):
            both.wait()
        return real(name)

    monkeypatch.setattr(store, "current", current)
    data = call(srv, "/_api/overview", who=OWNER)[1]
    assert sorted(r["name"] for r in data["reports"]) == ["a", "b", "c", "d"]


def test_name_cache_keeps_the_list_and_adds_a_publish(store, site):
    publish(store, site, "first", now=T1)
    names = NameCache(store, ttl=60)
    assert names.get() == ["first"]
    publish(store, site, "second", now=T1)
    assert names.get() == ["first"]  # within ttl: written around the gateway, not seen yet
    names.add("second")  # the gateway's own publish
    assert names.get() == ["first", "second"]
    assert NameCache(store, ttl=0).get() == ["first", "second"]


def test_label_cache_drops_a_read_overtaken_by_a_change(store, site, monkeypatch):
    publish(store, site, "report", now=T1)
    labels = LabelCache(store, ttl=60)
    reading, go = threading.Event(), threading.Event()
    real = store.labels

    def slow(name):
        old = real(name)
        reading.set()
        go.wait(5)
        return old

    monkeypatch.setattr(store, "labels", slow)
    read = threading.Thread(target=labels.get, args=("report",))
    read.start()
    assert reading.wait(5)
    labels.put("report", {"delivery": "server"})  # a change while the old read is under way
    go.set()
    read.join(5)
    monkeypatch.setattr(store, "labels", real)
    assert labels.get("report") == {"delivery": "server"}  # the old read was not kept


# --- the overview as it comes (/_api/overview?stream=1) ----------------------------------------


def stream(srv, who=OWNER, method="GET", headers=None):
    """(response, its lines): read line by line from a connection kept open by the caller."""
    conn = http.client.HTTPConnection("127.0.0.1", srv.server_port, timeout=5)
    sent = {"Host": host(srv), "Cookie": f"who={who}", **(headers or {})}
    conn.request(method, "/_api/overview?stream=1", headers=sent)
    resp = conn.getresponse()

    def lines():
        for raw in resp:
            yield json.loads(raw)

    return resp, lines()


def test_stream_sends_the_same_reports_line_by_line(local, store, site):
    publish(store, site, "report", published_by=OWNER, now=T1)
    publish(store, site, "theirs", published_by=OTHER, visibility="private", now=T1)
    publish(store, site, "gone", published_by=OWNER, now=T1)
    srv = local()
    assert call(srv, "/_api/pages/gone/delete", body={"deleted": True}, who=OWNER)[0] == 200
    resp, lines = stream(srv)
    assert resp.status == 200
    assert resp.getheader("Content-Type") == "application/x-ndjson"
    assert resp.getheader("Transfer-Encoding") == "chunked"
    head, *rows, last = list(lines)
    whole = call(srv, "/_api/overview", who=OWNER)[1]
    assert head == {**whole, "reports": [], "deleted": []}
    assert last == {"done": True}
    assert all(len(r) == 1 and len(next(iter(r.values()))) == 1 for r in rows)  # one each
    got = sorted((r["reports"][0] for r in rows if "reports" in r), key=lambda r: r["name"])
    assert got == sorted(whole["reports"], key=lambda r: r["name"])  # as read; the overview sorts
    assert [r["deleted"][0] for r in rows if "deleted" in r] == whole["deleted"]
    # No count of pages up front: it would include "theirs", which this viewer may not open.
    assert "theirs" not in json.dumps([head, *rows])


def test_stream_sends_a_report_while_another_is_still_read(local, store, site, monkeypatch):
    for name in ("fast", "slow"):
        publish(store, site, name, published_by=OWNER, now=T1)
    srv = local()
    go = threading.Event()
    real = store.current

    def current(name):
        if name == "slow":
            assert go.wait(5)
        return real(name)

    monkeypatch.setattr(store, "current", current)
    _, lines = stream(srv)
    assert next(lines)["reports"] == []  # the head, at once
    assert next(lines)["reports"][0]["name"] == "fast"  # while "slow" is still being read
    go.set()
    assert next(lines)["reports"][0]["name"] == "slow"
    assert next(lines) == {"done": True}


def test_stream_ends_with_an_error_line_not_done(local, store, site, monkeypatch):
    for name in ("good", "bad"):
        publish(store, site, name, published_by=OWNER, now=T1)
    srv = local()
    real = store.current

    def current(name):
        if name == "bad":
            raise ClientError({"Error": {"Code": "InternalError"}}, "GetObject")
        return real(name)

    monkeypatch.setattr(store, "current", current)
    resp, lines = stream(srv)
    got = list(lines)
    assert resp.status == 200 and got[-1] == {"error": "store error"}
    assert {"done": True} not in got
    assert request(srv, "/_health", host=host(srv))[0] == 200  # the gateway carries on


def test_stream_head_signed_out_and_cross_site(local, store, site):
    publish(store, site, "report", published_by=OWNER, now=T1)
    srv = local()
    resp, _ = stream(srv, method="HEAD")
    assert resp.status == 200 and resp.read() == b""
    path = "/_api/overview?stream=1"
    assert request(srv, path, host=host(srv), who=None)[0] == 401
    cross = {"Sec-Fetch-Site": "cross-site"}
    assert request(srv, path, host=host(srv), who=OWNER, headers=cross)[0] == 403


def test_overview_html_shows_loading_until_the_script_draws(local, store, site):
    srv = local()
    text = request(srv, "/", host=host(srv), who=OWNER)[2].decode()
    loading = text.index('class="page loading"')
    assert loading < text.index("<noscript>")
    assert "Loading reports" in text and 'role="status"' in text
