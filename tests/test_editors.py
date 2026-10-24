"""Editors: people the owner names who may change a page (edit text, publish, set current)
besides them, at any visibility. labels.json keeps `owner` and `editors`; the owner never moves."""

import json
import re
from datetime import UTC, datetime

import pytest
from helpers import FRAME, content, request
from test_api import call, files_of, upload
from test_edits import PAGE, body, change

from ontic_pages.cli import main
from ontic_pages.publish import publish
from ontic_pages.store import (
    MAX_PEOPLE,
    Store,
    check_editors,
    editors_of,
    may_change,
    owner_of,
)

T1 = datetime(2026, 10, 7, 15, 30, tzinfo=UTC)
OWNER = "owner@onticlabs.io"
EDITOR = "georg@onticlabs.io"
OTHER = "other@onticlabs.io"
WRITE = {"Content-Type": "application/json", "Origin": "https://pages.test",
         "Sec-Fetch-Site": "same-origin"}  # fmt: skip


def test_checks_and_rules():
    assert check_editors([EDITOR.upper(), EDITOR, ""], "onticlabs.io") == [EDITOR]
    with pytest.raises(ValueError, match="bad email"):
        check_editors(["x@gmail.com"], "onticlabs.io")
    with pytest.raises(ValueError, match=f"at most {MAX_PEOPLE} editors"):
        check_editors([f"e{i}@onticlabs.io" for i in range(MAX_PEOPLE + 1)])
    with pytest.raises(ValueError, match="a list"):
        check_editors(EDITOR)
    assert editors_of({"editors": [EDITOR.upper(), "not an email", 3]}) == (EDITOR,)
    assert editors_of({"editors": "georg"}) == editors_of({}) == ()
    assert owner_of({"owner": " Owner@onticlabs.io "}, OTHER) == "Owner@onticlabs.io"
    assert owner_of({"owner": ""}, OTHER) == owner_of({}, OTHER) == OTHER
    assert may_change(OWNER.upper(), OWNER, ()) is True
    assert may_change(EDITOR, OWNER, (EDITOR,), "onticlabs.io") is True
    assert may_change("x@gmail.com", OWNER, ("x@gmail.com",), "onticlabs.io") is False
    assert may_change(OTHER, OWNER, (EDITOR,)) is False
    assert may_change("", OWNER, ("",)) is False


def test_publish_keeps_owner_and_editors(store, site):
    first = publish(store, site, "report", published_by=OWNER, now=T1)
    labels = store.labels("report")
    assert (labels["owner"], labels["editors"]) == (OWNER, [])  # on record from the start
    store.set_labels("report", {**labels, "editors": [EDITOR]})
    # An editor's version: the owner stays, the version's publisher is the editor (provenance).
    second = publish(store, site, "report", published_by=EDITOR)
    labels = store.labels("report")
    assert (labels["owner"], labels["editors"]) == (OWNER, [EDITOR])
    assert store.meta("report", second["version"])["published_by"] == EDITOR
    # A page from before editors: the owner goes on record as the publisher of the version
    # the new one replaces, not the new publisher.
    store.set_labels("report", {"delivery": "server"})
    store.set_current("report", first["version"])
    publish(store, site, "report", published_by=EDITOR)
    assert store.labels("report")["owner"] == OWNER


def opens(server, who) -> tuple[int, int, int]:
    return (
        request(server, "/report/", who=who)[0],
        content(server, "report", "/", who=who, headers=FRAME)[0],
        content(server, "report", "/style.css", who=who)[0],
    )


def post(server, path, data, who=OWNER):
    status, _, out = request(server, f"/_api/pages/report/{path}", who=who, headers=WRITE,
                             method="POST", body=json.dumps(data).encode())  # fmt: skip
    return status, json.loads(out)


@pytest.fixture
def page(store, site):
    (site / "index.html").write_text(PAGE, newline="")
    return publish(store, site, "report", "first", published_by=OWNER, now=T1)


def test_gateway_editors(store, serve, page):
    server = serve()
    facts = json.loads(request(server, "/_api/pages/report", who=EDITOR)[2])
    assert (facts["editors"], facts["role"]) == ([], "viewer")

    # Only the owner names editors, the whole list each time; the owner is never on it.
    status, answer = post(server, "editors", {"editors": [EDITOR]}, who=EDITOR)
    assert (status, answer) == (403, {"error": "only the owner can change this"})
    status, answer = post(server, "editors", {"editors": ["x@gmail.com"]})
    assert status == 400 and "editors are team accounts at @onticlabs.io" in answer["error"]
    assert post(server, "editors", {"editors": EDITOR})[0] == 400
    status, answer = post(server, "editors", {"editors": [EDITOR.upper(), OWNER]})
    assert (status, answer["editors"], answer["role"]) == (200, [EDITOR], "owner")
    labels = store.labels("report")
    assert (labels["owner"], labels["editors"]) == (OWNER, [EDITOR])
    for who, role in ((EDITOR, "editor"), (OTHER, "viewer"), (OWNER, "owner")):
        facts = json.loads(request(server, "/_api/pages/report", who=who)[2])
        assert (facts["editors"], facts["role"], facts["published_by"]) == ([EDITOR], role, OWNER)
    # The Share panel shows the list; signed out, nothing.
    assert 'id="s-editors"' in request(server, "/report/", who=EDITOR)[2].decode()
    assert post(server, "visibility", {"visibility": "public"})[0] == 200
    facts = json.loads(request(server, "/_api/pages/report", who=None)[2])
    assert (facts["editors"], facts["people"], facts["role"]) == ([], [], "viewer")
    assert post(server, "visibility", {"visibility": "ontic"})[0] == 200

    # The editor edits text; the owner stays the owner, the version is the editor's.
    data = body(page, change("Results", "Findings"))
    assert post(server, "edits", data, who=OTHER)[0] == 403
    status, answer = post(server, "edits", data, who=EDITOR)
    assert status == 200 and answer["page"]["role"] == "editor"
    new = answer["version"]
    assert store.current("report") == new
    assert store.meta("report", new)["published_by"] == EDITOR
    assert answer["page"]["published_by"] == OWNER
    assert store.labels("report")["owner"] == OWNER
    facts = json.loads(request(server, "/_api/pages/report", who=OWNER)[2])
    assert (facts["role"], facts["published_by"], facts["editors"]) == ("owner", OWNER, [EDITOR])

    # The editor switches the current version; others do not.
    first = page["version"]
    assert post(server, "current", {"version": first}, who=OTHER)[0] == 403
    status, answer = post(server, "current", {"version": first}, who=EDITOR)
    assert (status, answer["current"], answer["role"]) == (200, first, "editor")
    # Only the owner shares, chooses delivery or deletes.
    owner_only = (("visibility", {"visibility": "public"}), ("delivery", {"delivery": "server"}))
    for path, data in owner_only:
        status, answer = post(server, path, data, who=EDITOR)
        assert (status, answer["error"]) == (403, "only the owner can change this"), path
    assert post(server, "delete", {}, who=EDITOR)[0] == 403

    # Taken off the list: a viewer again, and the owner stays on record.
    status, answer = post(server, "editors", {"editors": []})
    assert (status, answer["editors"]) == (200, [])
    assert post(server, "edits", body(page, change("Results", "Findings")), who=EDITOR)[0] == 403
    assert store.labels("report")["owner"] == OWNER
    facts = json.loads(request(server, "/_api/pages/report", who=EDITOR)[2])
    assert facts["role"] == "viewer"


def test_editors_open_a_private_page(store, serve, page):
    store.set_visibility("report", "private")
    store.set_labels("report", {**store.labels("report"), "editors": [EDITOR]})
    server = serve()
    assert opens(server, OWNER) == opens(server, EDITOR) == (200, 200, 200)
    assert opens(server, OTHER) == (403, 403, 403)
    # Listed for them like the people it is shared with, but kept apart from that list.
    listed = json.loads(request(server, "/_api/pages", who=EDITOR)[2])["pages"]
    assert [(p["name"], p["people"], p["editors"]) for p in listed] == [("report", [], [EDITOR])]
    assert json.loads(request(server, "/_api/pages", who=OTHER)[2])["pages"] == []
    overview = json.loads(request(server, "/_api/overview", who=EDITOR)[2])
    assert [(r["name"], r["author"], r["editors"]) for r in overview["reports"]] == [
        ("report", OWNER, [EDITOR])
    ]
    assert json.loads(request(server, "/_api/overview", who=OTHER)[2])["reports"] == []
    for path in ("/report/_info", "/_api/pages/report/info", "/_api/pages/report/comments"):
        assert request(server, path, who=EDITOR)[0] == 200, path
        assert request(server, path, who=OTHER)[0] == 403, path
    facts = json.loads(request(server, "/_api/pages/report", who=EDITOR)[2])
    assert (facts["people"], facts["editors"], facts["role"]) == ([], [EDITOR], "editor")


def test_editors_publish_a_version_only(local, store, site):
    publish(store, site, "report", published_by=OWNER, visibility="private", now=T1)
    store.set_labels("report", {**store.labels("report"), "editors": [EDITOR]})
    srv = local()
    files = {"files": files_of(("index.html", 5))}
    assert call(srv, "/_api/pages/report/versions", OTHER, files)[0] == 403
    # Who may open the page is the owner's call.
    start = "/_api/pages/report/versions"
    status, answer = call(srv, start, EDITOR, {**files, "visibility": "public"})
    assert status == 403 and f"only {OWNER} can change who may open report" in answer["error"]
    assert call(srv, start, EDITOR, {**files, "people": [OTHER]})[0] == 403
    status, answer = call(srv, "/_api/pages/report/versions", EDITOR, files)
    assert status == 200 and re.fullmatch(r"\d{8}T\d{6}Z", version := answer["version"])
    upload(answer, {"index.html": b"<p/>!"})
    status, done = call(srv, f"/_api/pages/report/versions/{version}/commit", EDITOR, {})
    assert status == 200 and done["page"]["published_by"] == EDITOR
    assert store.current("report") == version and store.visibility("report") == "private"
    labels = store.labels("report")
    assert (labels["owner"], labels["editors"]) == (OWNER, [EDITOR])
    # The owner publishes as before, with the level.
    assert call(srv, start, OWNER, {**files, "visibility": "ontic"})[0] == 200
    # A deleted page is the owner's to bring back: not an editor's to publish onto.
    store.set_labels("report", {**store.labels("report"), "deleted": True})
    assert call(srv, "/_api/pages/report/versions", EDITOR, files)[0] == 404
    assert call(srv, "/_api/pages/report/versions", OWNER, files)[0] == 200


def test_cli_direct(cli_env, site, capsys, monkeypatch):
    monkeypatch.setenv("ONTIC_PAGES_EMAIL", OWNER)
    store = Store(cli_env, "test-bucket")
    main(["publish", str(site), "--name", "report"])
    capsys.readouterr()
    with pytest.raises(SystemExit, match="give a level"):
        main(["share", "report"])
    with pytest.raises(SystemExit, match="bad email"):
        main(["share", "report", "--edit", "x@gmail.com"])
    main(["share", "report", "--edit", EDITOR.upper(), "--edit", OWNER])
    out = capsys.readouterr().out
    assert f"editors: {EDITOR} can edit it" in out and "is now" not in out  # the level stayed
    labels = store.labels("report")
    assert (labels["editors"], labels["owner"]) == ([EDITOR], OWNER)
    assert store.access("report") == ("ontic", ())
    main(["share", "report", "private", "--with", OTHER, "--edit", EDITOR])  # both at once
    assert store.access("report") == ("private", (OTHER,))
    main(["info", "report"])
    assert f"editors      {EDITOR}" in capsys.readouterr().out
    main(["list"])
    assert f"shared with {OTHER}  editors {EDITOR}" in capsys.readouterr().out
    main(["publish", str(site), "--name", "report"])  # a publish keeps both
    assert store.labels("report")["editors"] == [EDITOR]
    main(["share", "report", "--no-editors"])
    assert "editors: none" in capsys.readouterr().out
    assert store.labels("report")["editors"] == []
    with pytest.raises(SystemExit, match="takes no --edit"):
        main(["share", "report", "--no-editors", "--edit", EDITOR])
