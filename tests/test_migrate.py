"""The pure parts and the write path of scripts/migrate_old_pages.py (no ontic needed)."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from ontic_pages.store import Store

spec = importlib.util.spec_from_file_location(
    "migrate", Path(__file__).parents[1] / "scripts" / "migrate_old_pages.py"
)
migrate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migrate)


def test_slug_and_unique_name():
    assert migrate.slug("Ontic Pages: getting started guide") == "ontic-pages-getting-started-guide"
    long = migrate.slug("Plan for a GAE-style compressor on frozen VGGT-Omega: architecture, more")
    assert long == "plan-for-a-gae-style-compressor-on-frozen-vggt-omega-architecture"[:52]
    assert len(migrate.slug("x" * 100)) == 64
    assert migrate.slug("!!!") == ""
    taken = {"report"}
    assert migrate.unique_name("report", taken) == "report-2"
    assert migrate.unique_name("report", taken) == "report-3"


def test_version_id_and_order():
    used = set()
    assert migrate.version_id("2026-10-06T09:48:33.123456Z", used) == "20261006T094833Z"
    assert migrate.version_id("2026-10-06T11:48:33+02:00", used) == "20261006T094834Z"
    head = "h"
    assert migrate.version_ids(head, {}) == ["h"]
    assert migrate.version_ids(head, {"page": {"versions": ["h", "v2"]}}) == ["h", "v2"]


def test_git_and_visibility():
    assert migrate.VISIBILITY == {"private": "private", "team": "ontic", "public": "public"}
    sc = {"repository": "https://github.com/o/r", "commit": "abc", "branch": "main", "dirty": 1}
    assert migrate.to_git(sc) == {
        "remote": "https://github.com/o/r", "branch": "main", "commit": "abc", "dirty": True
    }  # fmt: skip
    assert migrate.to_git(None) is None


class OnticStoreLike:
    """The two read calls write() makes on the ontic store."""

    def __init__(self, s3, bucket):
        self.s3, self.bucket, self.client = s3, bucket, s3

    def exists(self, key):
        return (self.bucket, key) in self.s3.objects

    def get(self, key):
        return self.s3.objects[(self.bucket, key)][0]


def test_write_copies_and_is_rerunnable(s3, monkeypatch, capsys):
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    s3.put_object(Bucket="b", Key="jobs/j1/output/data/index.html", Body=b"<p>one</p>")
    s3.put_object(Bucket="b", Key="jobs/j2/output/data/index.html", Body=b"<p>two</p>")
    s3.put_object(Bucket="b", Key="jobs/j2/output/data/img/a.png", Body=b"png")
    page = {"name": "old", "description": "d", "meta": {}, "git": None}
    mapping = {
        "bucket": "b",
        "prefix": "pages/",
        "pages": [
            {
                "name": "renamed",
                "head": "j1",
                "current": "20261006T000000Z",
                "visibility": "private",
                "versions": [
                    {"version": "20261006T000000Z", "job": "j1", "files": {"index.html": 10},
                     "page": dict(page, version="x")},
                    {"version": "20261007T000000Z", "job": "j2",
                     "files": {"index.html": 10, "img/a.png": 3}, "page": dict(page)},
                ],
            }
        ],
    }  # fmt: skip
    ctx = SimpleNamespace(store=OnticStoreLike(s3, "b"))
    migrate.write(ctx, mapping)
    store = Store(s3, "b", "pages/")
    assert store.current("renamed") == "20261006T000000Z"
    assert store.visibility("renamed") == "private"
    assert store.versions("renamed") == ["20261006T000000Z", "20261007T000000Z"]
    assert s3.objects[("b", "pages/renamed/20261007T000000Z/img/a.png")] == (b"png", "image/png")
    meta = store.meta("renamed", "20261006T000000Z")
    assert (meta["name"], meta["version"]) == ("renamed", "20261006T000000Z")
    assert not any(c == "delete_object" for c in s3.calls)

    store.set_visibility("renamed", "public")  # changed after the migration: kept on a re-run
    copies = s3.calls.count("copy_object")
    migrate.write(ctx, mapping)
    assert s3.calls.count("copy_object") == copies  # nothing copied twice
    assert "already there" in capsys.readouterr().out
    assert store.visibility("renamed") == "public"

    store.set_current("renamed", "20991231T000000Z")  # someone else's version now
    migrate.write(ctx, mapping)
    assert "skip renamed" in capsys.readouterr().out
    assert store.current("renamed") == "20991231T000000Z"

    bad_level = dict(mapping, pages=[dict(mapping["pages"][0], visibility="team")])
    with pytest.raises(SystemExit, match="visibility must be"):
        migrate.write(ctx, bad_level)
    with pytest.raises(SystemExit, match="bad or duplicate"):
        migrate.write(ctx, dict(mapping, pages=mapping["pages"] * 2))
