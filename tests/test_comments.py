"""Comments: the file per page in the bucket and the cleaning of what people send."""

import json
from datetime import UTC, datetime

import pytest

from ontic_pages.comments import (
    BODY_LIMIT,
    Comments,
    clean_anchor,
    clean_body,
    display_name,
    listing,
)
from ontic_pages.publish import publish
from ontic_pages.uploads import Refused

T1 = datetime(2026, 10, 7, 15, 30, tzinfo=UTC)
T2 = datetime(2026, 10, 8, 9, 0, tzinfo=UTC)
OWNER = "owner@onticlabs.io"
OTHER = "other.person@onticlabs.io"
ANCHOR = {"path": "/", "selector": "#t > p:nth-of-type(2)", "fx": 0.25, "fy": 0.5,
          "snippet": "Depth error table", "x": 120, "y": 340}  # fmt: skip
KEY = ("test-bucket", "report/comments.json")


@pytest.fixture
def report(store, site):
    """report: two versions by OWNER, the second current."""
    first = publish(store, site, "report", "first", published_by=OWNER, now=T1)["version"]
    second = publish(store, site, "report", "second", published_by=OWNER, now=T2)["version"]
    return first, second


def saved(s3) -> dict:
    return json.loads(s3.objects[KEY][0])


# --- cleaning -----------------------------------------------------------------------------


def test_clean_body():
    assert clean_body("  hi\r\nthere\rnow\x00\x07\u202e \t") == "hi\nthere\nnow"
    assert clean_body("a\tb") == "a\tb"
    assert clean_body("x" * BODY_LIMIT) == "x" * BODY_LIMIT
    for bad in ("", "  \n\x01 ", None, 5, ["a"], "x" * (BODY_LIMIT + 1)):
        with pytest.raises(Refused) as err:
            clean_body(bad)
        assert err.value.status == 400


def test_clean_anchor():
    assert clean_anchor(ANCHOR) == {**ANCHOR, "x": 120.0, "y": 340.0}
    out = clean_anchor({"path": "/a?b=1", "selector": "p", "fx": 7, "fy": -1, "x": -5,
                        "y": 1e12, "snippet": "  many\n  spaces " + "z" * 100,
                        "extra": 1})  # fmt: skip
    assert out == {"path": "/a?b=1", "selector": "p", "fx": 1.0, "fy": 0.0,
                   "snippet": ("many spaces " + "z" * 100)[:60], "x": 0.0, "y": 1e7}  # fmt: skip
    assert clean_anchor({})["path"] == "/" and clean_anchor({})["fx"] == 0.5
    # Too deep or too long: dropped, the pin falls back to x, y.
    deep = " > ".join(["div"] * 9)
    assert clean_anchor({"selector": deep})["selector"] == ""
    assert clean_anchor({"selector": " > ".join(["div"] * 8)})["selector"].count(">") == 7
    assert clean_anchor({"selector": "p" * 1025})["selector"] == ""
    for bad in ([], "x", {"path": "a"}, {"path": "//evil.test/"}, {"path": "/" + "a" * 1024},
                {"fx": "1"}, {"x": True}, {"y": float("nan")}, {"selector": 5}):  # fmt: skip
        with pytest.raises(Refused):
            clean_anchor(bad)


def test_display_name():
    assert display_name("mikel@onticlabs.io") == "Mikel"
    assert display_name("other.person@onticlabs.io") == "Other Person"
    assert display_name("a_b-c+d@x") == "A B C D"
    assert display_name("") == ""


# --- the file -----------------------------------------------------------------------------


def test_threads_live_in_one_file(store, s3, report):
    _, v2 = report
    comments = Comments(store, ttl=60)
    assert comments.threads("report") == []
    t = comments.create("report", v2, ANCHOR, OTHER, "Row 3 looks off")
    assert len(t["id"]) == 16 and t["version"] == v2 and t["created_by"] == OTHER
    assert t["resolved_at"] is None and t["comments"][0]["body"] == "Row 3 looks off"
    assert s3.objects[KEY][1] == "application/json; charset=utf-8"
    comments.reply("report", t["id"], OWNER, "Fixed in the next version")
    comments.resolve("report", t["id"], True, OWNER)
    data = saved(s3)
    assert list(data) == ["threads"] and len(data["threads"]) == 1
    stored = data["threads"][0]
    assert stored["resolved_by"] == OWNER and stored["resolved_at"]
    assert [c["author"] for c in stored["comments"]] == [OTHER, OWNER]
    assert set(stored["comments"][1]) == {"id", "author", "body", "created_at", "deleted"}
    # Reopen; resolving twice changes nothing.
    puts = s3.calls.count("put_object")
    comments.resolve("report", t["id"], False, OTHER)
    comments.resolve("report", t["id"], False, OTHER)
    assert s3.calls.count("put_object") == puts + 1
    assert saved(s3)["threads"][0]["resolved_by"] is None
    # The page's versions are untouched; comments.json is not a version.
    assert store.versions("report") == list(report)


def test_delete_is_a_tombstone(store, s3, report):
    comments = Comments(store, ttl=0)
    t = comments.create("report", report[1], ANCHOR, OTHER, "first")
    t = comments.reply("report", t["id"], OWNER, "second")
    first, second = (c["id"] for c in t["comments"])
    with pytest.raises(Refused) as err:
        comments.delete("report", t["id"], first, OWNER)  # not theirs, even for the owner
    assert err.value.status == 403
    t = comments.delete("report", t["id"], first, OTHER.upper())
    assert t["comments"][0] == {**t["comments"][0], "deleted": True, "body": ""}
    assert saved(s3)["threads"][0]["comments"][0]["deleted"] is True
    assert len(saved(s3)["threads"][0]["comments"]) == 2  # still there
    with pytest.raises(Refused) as err:
        comments.delete("report", t["id"], "0" * 16, OTHER)
    assert err.value.status == 404
    with pytest.raises(Refused) as err:
        comments.reply("report", "f" * 16, OTHER, "x")
    assert err.value.status == 404
    assert "delete_object" not in s3.calls


def test_cache_and_reread(store, s3, report):
    comments = Comments(store, ttl=60)
    comments.create("report", report[1], ANCHOR, OTHER, "one")
    s3.calls.clear()
    assert len(comments.threads("report")) == 1
    assert s3.calls == []  # from memory
    # Written elsewhere (another gateway): seen once the ttl is over.
    data = saved(s3)
    data["threads"].append({**data["threads"][0], "id": "a" * 16})
    store.put(store.key("report", "comments.json"), json.dumps(data).encode())
    assert len(comments.threads("report")) == 1
    comments.ttl = 0
    assert len(comments.threads("report")) == 2


def test_unreadable_file_is_never_overwritten(store, s3, report):
    store.put(store.key("report", "comments.json"), b"{not json")
    comments = Comments(store, ttl=0)
    with pytest.raises(Refused) as err:
        comments.create("report", report[1], ANCHOR, OTHER, "x")
    assert err.value.status == 502
    assert s3.objects[KEY][0] == b"{not json"


def test_limits(store, report, monkeypatch):
    monkeypatch.setattr("ontic_pages.comments.MAX_THREADS", 2)
    monkeypatch.setattr("ontic_pages.comments.MAX_COMMENTS", 2)
    comments = Comments(store, ttl=0)
    t = comments.create("report", report[1], ANCHOR, OTHER, "1")
    comments.create("report", report[1], ANCHOR, OTHER, "2")
    with pytest.raises(Refused) as err:
        comments.create("report", report[1], ANCHOR, OTHER, "3")
    assert err.value.status == 409
    comments.reply("report", t["id"], OTHER, "r")
    with pytest.raises(Refused):
        comments.reply("report", t["id"], OTHER, "r2")


def test_listing():
    def c(author, when):
        return {"id": when[-2:] * 8, "author": author, "body": "b", "created_at": when,
                "deleted": False}  # fmt: skip

    old = {"id": "a" * 16, "created_by": OTHER, "created_at": "2026-10-01T00:00:01",
           "resolved_at": None, "comments": [c(OTHER, "2026-10-01T00:00:01"),
                                             c(OWNER, "2026-10-05T00:00:00")]}  # fmt: skip
    new = {"id": "b" * 16, "created_by": OWNER, "created_at": "2026-10-03T00:00:00",
           "resolved_at": "2026-10-04T00:00:00", "resolved_by": OTHER,
           "comments": [c(OWNER, "2026-10-03T00:00:00")]}  # fmt: skip
    views = listing([new, old], OWNER)
    assert [v["id"] for v in views] == ["a" * 16, "b" * 16]  # the latest reply counts
    first = views[0]
    assert first["created_by_name"] == "Other Person" and first["resolved"] is False
    assert first["updated_at"] == "2026-10-05T00:00:00"
    assert [(x["author_name"], x["mine"]) for x in first["comments"]] == [
        ("Other Person", False),
        ("Owner", True),
    ]
    assert views[1]["resolved"] is True and views[1]["resolved_by_name"] == "Other Person"
