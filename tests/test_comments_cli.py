"""`comments`, `comment` and `resolve` through the gateway, as an agent answering feedback."""

import io
import json
from datetime import UTC, datetime

import pytest

from ontic_pages import comments_cli
from ontic_pages.cli import main
from ontic_pages.comments import Comments
from ontic_pages.publish import publish

T1 = datetime(2026, 10, 7, 15, 30, tzinfo=UTC)
T2 = datetime(2026, 10, 8, 9, 0, tzinfo=UTC)
OWNER = "owner@onticlabs.io"
OTHER = "other@onticlabs.io"
ANCHOR = {"path": "/", "selector": "h1", "snippet": "version one", "x": 10, "y": 20}


@pytest.fixture
def threads(store, site):
    """report by OWNER (two versions); OTHER left two threads, one on the old version, and
    one more that is resolved."""
    v1 = publish(store, site, "report", "first", published_by=OWNER, now=T1)["version"]
    v2 = publish(store, site, "report", "second", published_by=OWNER, now=T2)["version"]
    comments = Comments(store, ttl=0)
    a = comments.create("report", v2, ANCHOR, OTHER, "The title is wrong\nand too long")
    b = comments.create("report", v1, {**ANCHOR, "path": "/docs/", "tag": "h1"}, OTHER, "Old remark")
    c = comments.create("report", v2, ANCHOR, OTHER, "Done already")
    comments.resolve("report", c["id"], True, OWNER)
    return comments, a["id"], b["id"], c["id"], v1


def test_comments_list(local, gateway_env, threads, capsys):
    comments, a, b, c, v1 = threads
    gateway_env(local(), OWNER)
    main(["comments", "report"])
    out = capsys.readouterr().out
    assert out.startswith("2 threads on report (1 resolved, not shown: --all shows them)")
    assert f'{a[:6]}  open  /  "version one"\n' in out
    assert f"  {OTHER}, " in out and "    The title is wrong\n    and too long" in out
    assert f'{b[:6]}  open  /docs/  <h1>  "version one"' in out and f"(made on version {v1})" in out
    assert c[:6] not in out and "Done already" not in out

    main(["comments", "report", "--all"])
    out = capsys.readouterr().out
    assert out.startswith("3 threads on report,")
    assert f"{c[:6]}  resolved" in out and f"resolved by {OWNER}" in out

    main(["comments", "report", "--json"])
    answer = json.loads(capsys.readouterr().out)
    assert {t["id"] for t in answer["threads"]} == {a, b} and answer["open"] == 2

    comments.delete("report", a, comments.threads("report")[0]["comments"][0]["id"], OTHER)
    main(["comments", "report"])
    assert "    (deleted)" in capsys.readouterr().out


def test_reply_and_resolve(local, gateway_env, threads, store, capsys, monkeypatch):
    comments, a, b, c, _ = threads
    gateway_env(local(), OWNER)
    main(["comment", "report", a[:6], "Fixed: shorter title"])
    assert capsys.readouterr().out.strip() == f"replied to {a[:6]} on report"
    monkeypatch.setattr("sys.stdin", io.StringIO("From stdin\nwith two lines\n"))
    main(["comment", "report", a, "-"])
    capsys.readouterr()
    thread = next(t for t in comments.threads("report") if t["id"] == a)
    assert [(x["author"], x["body"]) for x in thread["comments"][1:]] == [
        (OWNER, "Fixed: shorter title"),
        (OWNER, "From stdin\nwith two lines"),
    ]
    main(["resolve", "report", a[:8]])
    assert capsys.readouterr().out.strip() == f"resolved {a[:6]} on report"
    assert next(t for t in comments.threads("report") if t["id"] == a)["resolved_by"] == OWNER
    main(["resolve", "report", c[:6], "--reopen"])
    assert capsys.readouterr().out.strip() == f"reopened {c[:6]} on report"
    assert next(t for t in comments.threads("report") if t["id"] == c)["resolved_at"] is None


def test_thread_ids(local, gateway_env, threads):
    _, a, *_ = threads
    gateway_env(local(), OWNER)
    with pytest.raises(SystemExit, match="too short"):
        main(["comment", "report", a[:3], "x"])
    with pytest.raises(SystemExit, match="no comment thread .* on report"):
        main(["resolve", "report", "0000" if not a.startswith("0000") else "ffff"])
    with pytest.raises(SystemExit, match="the comment is empty"):
        main(["comment", "report", a, "   "])
    answer = {"name": "p", "threads": [{"id": "abcd" + "0" * 12}, {"id": "abcd" + "1" * 12}]}
    with pytest.raises(SystemExit, match="matches 2 threads"):
        comments_cli.find(answer, "abcd")
    assert comments_cli.find(answer, "abcd1")["id"] == "abcd" + "1" * 12


def test_short_ids():
    ids = ["abcdef0" + "1" * 9, "abcdef0" + "2" * 9, "1234567" + "8" * 9]
    assert comments_cli.short_ids(ids) == {
        ids[0]: "abcdef01",
        ids[1]: "abcdef02",
        ids[2]: "123456",
    }


def test_waits_when_rate_limited(local, gateway_env, threads, monkeypatch, capsys):
    _, a, *_ = threads
    monkeypatch.setattr(comments_cli, "WAIT_SECONDS", 0)
    hits = []

    def twice_no(self, who):
        hits.append(who)
        return len(hits) > 2

    monkeypatch.setattr("ontic_pages.auth.RateLimit.allow", twice_no)
    gateway_env(local(), OWNER)
    main(["comment", "report", a, "after waiting"])
    out = capsys.readouterr()
    assert out.err.count("too many changes this minute, waiting") == 2
    assert out.out.strip() == f"replied to {a[:6]} on report"


def test_not_signed_in(local, gateway_env, threads):
    gateway_env(local())
    for argv in (["comments", "report"], ["comment", "report", "abcdef", "x"],
                 ["resolve", "report", "abcdef"]):  # fmt: skip
        with pytest.raises(SystemExit, match="run ontic-pages login"):
            main(argv)
