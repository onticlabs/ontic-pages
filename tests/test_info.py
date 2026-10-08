from datetime import UTC, datetime

import pytest
from helpers import request

from ontic_pages.cli import main
from ontic_pages.info import github_url, short
from ontic_pages.publish import publish
from ontic_pages.store import Store

T1 = datetime(2026, 10, 7, 15, 30, tzinfo=UTC)
T2 = datetime(2026, 10, 8, 9, 0, tzinfo=UTC)
GIT = {
    "remote": "git@github.com:onticlabs/experiments.git",
    "branch": "main",
    "commit": "0123456789abcdef0123456789abcdef01234567",
    "dirty": True,
}
LONG = "A very long description that goes on and on about depth estimation results"


def test_github_url():
    for remote in (
        "git@github.com:onticlabs/x.git",
        "https://github.com/onticlabs/x",
        "https://github.com/onticlabs/x.git",
        "ssh://git@github.com/onticlabs/x.git",
    ):
        assert github_url(remote) == "https://github.com/onticlabs/x"
    assert github_url("https://gitlab.com/a/b") is None
    assert github_url(None) is None


def test_short():
    assert short("abc", 5) == '<span title="abc">abc</span>'
    cut = short("a<b> " + "x" * 20, 8)
    assert cut == '<span title="a&lt;b&gt; xxxxxxxxxxxxxxxxxxxx">a&lt;b&gt; xx…</span>'


def publish_two(store, site, monkeypatch):
    monkeypatch.setattr("ontic_pages.publish.git_provenance", lambda cwd: GIT)
    first = publish(store, site, "report", "first <i>try</i>", {"seed": "7"}, now=T1)
    publish(store, site, "report", LONG, now=T2)
    store.set_current("report", first["version"])
    return first


def test_page_json_fields(store, site, monkeypatch):
    first = publish_two(store, site, monkeypatch)
    saved = store.meta("report", first["version"])
    assert list(saved) == [
        "name", "version", "published_at", "published_by", "description", "meta", "git", "files",
    ]  # fmt: skip
    assert "inputs" not in saved


def test_info_page(store, site, monkeypatch, serve):
    publish_two(store, site, monkeypatch)
    srv = serve()
    status, headers, body = request(srv, "/report/_info")
    listing = request(srv, "/")[2].decode()
    assert request(srv, "/nope/_info")[0] == 404
    text = body.decode()
    assert status == 200 and headers["Content-Type"] == "text/html; charset=utf-8"
    assert "<script" not in text
    assert "first &lt;i&gt;try&lt;/i&gt;" in text
    assert "<th>Visibility</th><td>ontic</td>" in text
    assert "<th>seed</th><td>7</td>" in text
    assert '<a href="https://github.com/onticlabs/experiments">' in text
    assert (
        '<a href="https://github.com/onticlabs/experiments/commit/'
        '0123456789abcdef0123456789abcdef01234567">01234567</a>'
    ) in text
    assert "uncommitted changes" in text
    assert "<tr class=current><td>20261007T153000Z (current)</td>" in text
    assert f'<span title="{LONG}">{LONG[:59].rstrip()}…</span>' in text
    assert '<a href="/report/_info">info</a>' in listing


def test_info_command(cli_env, site, monkeypatch, capsys):
    store = Store(cli_env, "test-bucket")
    publish_two(store, site, monkeypatch)
    main(["info", "report"])
    out = capsys.readouterr().out
    assert "visibility   ontic" in out
    assert "current      20261007T153000Z" in out
    assert "meta         seed = 7" in out
    assert "input" not in out
    assert "git@github.com:onticlabs/experiments.git main 01234567 (uncommitted changes)" in out
    assert "  * 20261007T153000Z" in out and "    20261008T090000Z" in out
    with pytest.raises(SystemExit, match="no page named"):
        main(["info", "ghost"])


def test_from_is_gone(cli_env, site):
    with pytest.raises(SystemExit):
        main(["publish", str(site), "--name", "r", "--from", "model:x"])
