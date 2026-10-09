"""`ontic-pages pull`: a version's files, straight from the bucket with presigned GET URLs."""

import json
from datetime import UTC, datetime

import pytest
from helpers import SECRET, request

from ontic_pages.cli import main
from ontic_pages.edits import save
from ontic_pages.publish import publish
from ontic_pages.tokens import sign

T1 = datetime(2026, 10, 7, 15, 30, tzinfo=UTC)
OWNER = "owner@onticlabs.io"
OTHER = "other@onticlabs.io"
FILES = ["app.js", "data.json", "docs/index.html", "img/dot.png", "index.html", "style.css"]


def files_api(srv, path, email):
    headers = {"Authorization": f"Bearer {sign(SECRET, email)}"} if email else {}
    status, _, out = request(srv, path, host=srv.url.removeprefix("http://"), who=None,
                             headers=headers)  # fmt: skip
    return status, json.loads(out)


def tree(root):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def test_files_route(local, store, site, uploads):
    first = publish(store, site, "report", "one", published_by=OWNER, now=T1)["version"]
    current = publish(store, site, "report", "two", published_by=OWNER)["version"]
    publish(store, site, "mine", visibility="private", published_by=OWNER, now=T1)
    srv = local()
    status, answer = files_api(srv, "/_api/pages/report/files", OTHER)
    assert status == 200 and (answer["name"], answer["version"]) == ("report", current)
    assert answer["page"]["description"] == "two"
    assert [f["path"] for f in answer["files"]] == FILES  # no page.json
    item = answer["files"][-1]
    assert item["size"] == len("h1 { color: red }")
    assert item["url"].startswith(f"http://127.0.0.1:{uploads.server_port}/test-bucket/report/")
    assert "get=1" in item["url"] and "expires=3600" in item["url"]
    status, answer = files_api(srv, f"/_api/pages/report/files?version={first}", OTHER)
    assert (status, answer["version"]) == (200, first)
    assert files_api(srv, "/_api/pages/report/files?version=20990101T000000Z", OTHER)[0] == 404
    assert files_api(srv, "/_api/pages/report/files?version=x", OTHER)[0] == 404
    assert files_api(srv, "/_api/pages/report/files", None)[0] == 401
    assert files_api(srv, "/_api/pages/mine/files", OTHER)[0] == 403
    assert files_api(srv, "/_api/pages/ghost/files", OTHER)[0] == 404


def test_pull_through_the_gateway(
    local, gateway_env, store, site, uploads, tmp_path, capsys, monkeypatch
):
    monkeypatch.setattr("ontic_pages.pull.RETRY_SECONDS", 0)
    page = publish(store, site, "report", published_by=OWNER, now=T1)
    edited = save(store, "report", OWNER, {
        "version": page["version"], "path": "/", "changes": [{"before": "version one",
                                                              "after": "version 1"}],
    })  # fmt: skip
    srv = local()
    gateway_env(srv, OTHER)
    dest = tmp_path / "pulled"
    uploads.fail.append(1)  # one download fails once and is tried again
    main(["pull", "report", str(dest)])
    out = capsys.readouterr().out
    assert f"pulled report version {edited['version']} (6 files) into {dest}" in out
    assert f"edited in the browser by {OWNER}, from version {page['version']}" in out
    assert tree(dest) == FILES
    assert (dest / "index.html").read_text() == "<h1>version 1</h1>"
    assert (dest / "img" / "dot.png").read_bytes() == (site / "img" / "dot.png").read_bytes()
    assert len(uploads.gets) == 7  # every byte from the bucket's URLs
    # An older version, into a folder that exists but is empty.
    (tmp_path / "old").mkdir()
    main(["pull", "report", str(tmp_path / "old"), "--version", page["version"]])
    assert (tmp_path / "old" / "index.html").read_text() == "<h1>version one</h1>"
    assert "edited in the browser" not in capsys.readouterr().out
    with pytest.raises(SystemExit, match="not an empty folder"):
        main(["pull", "report", str(dest)])
    with pytest.raises(SystemExit, match="no version"):
        main(["pull", "report", str(tmp_path / "x"), "--version", "nope"])


def test_pull_refuses_paths_outside_the_folder(tmp_path):
    from ontic_pages.pull import download

    with pytest.raises(SystemExit, match="refusing the file path"):
        download([{"path": "../evil.html", "url": "http://127.0.0.1:9/"}], tmp_path / "d")
    assert not (tmp_path / "evil.html").exists()


def test_pull_direct(cli_env, site, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    main(["publish", str(site), "--name", "report"])
    capsys.readouterr()
    main(["pull", "report"])
    assert tree(tmp_path / "report") == FILES
    assert "pulled report version" in capsys.readouterr().out
    assert "generate_presigned_url" not in cli_env.calls
    with pytest.raises(SystemExit, match="no version"):
        main(["pull", "ghost", str(tmp_path / "g")])
