"""The overview's cost: no page reads for its HTML, one listing, page states read in parallel,
and the caches that keep it cheap (gateway.Gateway.openable, cache.NameCache, LabelCache)."""

import threading
from datetime import UTC, datetime

from helpers import request
from test_research import OWNER, call, host

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
