import json
import threading
from datetime import UTC, datetime

import pytest
from test_gateway import get

from ontic_pages.cli import main
from ontic_pages.gateway import make_server
from ontic_pages.info import github_url
from ontic_pages.publish import parse_input, publish
from ontic_pages.store import Store

T1 = datetime(2026, 10, 7, 15, 30, tzinfo=UTC)
T2 = datetime(2026, 10, 8, 9, 0, tzinfo=UTC)
GIT = {
    "remote": "git@github.com:onticlabs/experiments.git",
    "branch": "main",
    "commit": "0123456789abcdef0123456789abcdef01234567",
    "dirty": True,
}


def test_parse_input():
    assert parse_input("model:da3-backbone") == {"kind": "model", "ref": "da3-backbone"}
    assert parse_input("dataset:point-clouds-arctic@sha256:9f1c") == {
        "kind": "dataset",
        "ref": "point-clouds-arctic",
        "hash": "sha256:9f1c",
    }
    assert parse_input("run:onticlabs/fwomo/abc12")["ref"] == "onticlabs/fwomo/abc12"
    assert parse_input("job:j-123@j-456")["hash"] == "j-456"
    for bad in ("da3", "weights:x", "model:", "model:  ", "model:x@", ":x"):
        with pytest.raises(ValueError, match="KIND:REF"):
            parse_input(bad)


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


def publish_two(store, site, monkeypatch):
    monkeypatch.setattr("ontic_pages.publish.git_provenance", lambda cwd: GIT)
    inputs = [parse_input("model:da3@sha256:abc"), parse_input("run:wandb/xyz")]
    first = publish(store, site, "report", "first <i>try</i>", {"seed": "7"}, inputs, now=T1)
    publish(store, site, "report", "second", now=T2)
    store.set_current("report", first["version"])
    return first


def test_page_json_records_inputs(store, site, monkeypatch):
    first = publish_two(store, site, monkeypatch)
    saved = json.loads(store.read_text(store.key("report", first["version"], "page.json")))
    assert saved["inputs"] == [
        {"kind": "model", "ref": "da3", "hash": "sha256:abc"},
        {"kind": "run", "ref": "wandb/xyz"},
    ]
    assert list(saved) == [
        "name", "version", "published_at", "published_by", "description",
        "inputs", "meta", "git", "files",
    ]  # fmt: skip


def test_info_page(store, site, monkeypatch):
    publish_two(store, site, monkeypatch)
    srv = make_server(store, "127.0.0.1", 0, ttl=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        status, headers, body = get(srv, "/report/_info")
        listing = get(srv, "/")[2].decode()
        assert get(srv, "/nope/_info")[0] == 404
    finally:
        srv.shutdown()
        srv.server_close()
    text = body.decode()
    assert status == 200 and headers["Content-Type"] == "text/html; charset=utf-8"
    assert "<script" not in text
    assert "first &lt;i&gt;try&lt;/i&gt;" in text
    assert "<li>model: da3 @ sha256:abc</li>" in text and "<li>run: wandb/xyz</li>" in text
    assert "<th>seed</th><td>7</td>" in text
    assert '<a href="https://github.com/onticlabs/experiments">' in text
    assert (
        '<a href="https://github.com/onticlabs/experiments/commit/'
        '0123456789abcdef0123456789abcdef01234567">01234567</a>'
    ) in text
    assert "uncommitted changes" in text
    assert "<b>20261007T153000Z" in text and "(current)</b>" in text
    assert "20261008T090000Z" in text
    assert '<a href="/report/_info">info</a>' in listing


def test_info_command(cli_env, site, monkeypatch, capsys):
    store = Store(cli_env, "test-bucket", "pages/")
    publish_two(store, site, monkeypatch)
    main(["info", "report"])
    out = capsys.readouterr().out
    assert "current      20261007T153000Z" in out
    assert "input        model: da3 @ sha256:abc" in out
    assert "meta         seed = 7" in out
    assert "git@github.com:onticlabs/experiments.git main 01234567 (uncommitted changes)" in out
    assert "  * 20261007T153000Z" in out and "    20261008T090000Z" in out
    with pytest.raises(SystemExit, match="no page named"):
        main(["info", "ghost"])


def test_cli_publish_from(cli_env, site, capsys):
    main(["publish", str(site), "--name", "r", "--from", "checkpoint:ckpt-9@abc", "--meta", "a=b"])
    page = next(json.loads(v[0]) for k, v in cli_env.objects.items() if k[1].endswith("page.json"))
    assert page["inputs"] == [{"kind": "checkpoint", "ref": "ckpt-9", "hash": "abc"}]
    assert page["meta"] == {"a": "b"}
    with pytest.raises(SystemExit, match="KIND:REF"):
        main(["publish", str(site), "--name", "r", "--from", "weights:x"])
