"""A private page shared with a few named people: the rule, the visibility file, the gateway and
the command line."""

import json
from datetime import UTC, datetime

import pytest
from helpers import FRAME, ORIGIN, content, request

from ontic_pages import remote
from ontic_pages.auth import allowed
from ontic_pages.cli import main
from ontic_pages.publish import publish
from ontic_pages.store import MAX_PEOPLE, VISIBILITIES, Store, check_people

T1 = datetime(2026, 10, 7, 15, 30, tzinfo=UTC)
OWNER = "owner@onticlabs.io"
FRIEND = "friend@onticlabs.io"
OTHER = "other@onticlabs.io"
WRITE = {"Content-Type": "application/json", "Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"}


def test_allowed_with_people():
    people = (FRIEND, "x@gmail.com")
    rules = [
        (OWNER, True),
        ("Friend@OnticLabs.io ", True),
        (OTHER, False),  # on the team, not on the list
        ("x@gmail.com", False),  # listed, but not at the domain
        ("", False),
    ]
    for email, expected in rules:
        assert allowed("private", OWNER, email, "onticlabs.io", people) is expected, email
    assert allowed("private", OWNER, FRIEND, "onticlabs.io") is False  # no list, owner only


def test_visibility_file_round_trip(store, s3, site):
    publish(store, site, "report", now=T1)
    store.set_visibility(
        "report", "private", ["B@onticlabs.io", " a@onticlabs.io", "b@onticlabs.io"]
    )
    text = s3.objects[("test-bucket", "report/visibility")][0]
    assert text == b"private\na@onticlabs.io\nb@onticlabs.io"
    assert store.access("report") == ("private", ("a@onticlabs.io", "b@onticlabs.io"))
    assert store.visibility("report") == "private"
    # A gateway from before people strips the file and finds no level in it: private, owner only.
    assert text.decode().strip() not in VISIBILITIES
    # Files from before people, and lines that are no email, are read as before.
    for written, expected in [
        (b"private", ("private", ())),
        (b"public\n", ("public", ())),
        (b"ontic\nfriend@onticlabs.io", ("ontic", ())),
        (b"private\nnot an email\n\nFRIEND@onticlabs.io\n", ("private", (FRIEND,))),
        (b"team\nfriend@onticlabs.io", ("private", ())),
    ]:
        store.put(store.key("report", "visibility"), written)
        assert store.access("report") == expected, written
    store.set_visibility("report", "private")  # no list: nobody else
    assert s3.objects[("test-bucket", "report/visibility")][0] == b"private"


def test_people_checks():
    assert check_people("private", [FRIEND, FRIEND.upper()], "onticlabs.io") == [FRIEND]
    with pytest.raises(ValueError, match="only a private page"):
        check_people("ontic", [FRIEND])
    with pytest.raises(ValueError, match="bad email"):
        check_people("private", ["x@gmail.com"], "onticlabs.io")
    with pytest.raises(ValueError, match="bad email"):
        check_people("private", ["not an email"])
    with pytest.raises(ValueError, match=f"at most {MAX_PEOPLE}"):
        check_people("private", [f"p{i}@onticlabs.io" for i in range(MAX_PEOPLE + 1)])
    with pytest.raises(ValueError, match="a list"):
        check_people("private", FRIEND)


def post(server, body, who=OWNER):
    status, _, out = request(server, "/_api/pages/report/visibility", who=who, headers=WRITE,
                             method="POST", body=json.dumps(body).encode())  # fmt: skip
    return status, json.loads(out)


def opens(server, who) -> tuple[int, int, int]:
    """The shell, the page in the frame, and a file asked for directly."""
    return (
        request(server, "/report/", who=who)[0],
        content(server, "report", "/", who=who, headers=FRAME)[0],
        content(server, "report", "/style.css", who=who)[0],
    )


def test_gateway_shares_with_people(store, site, serve):
    publish(store, site, "report", visibility="private", published_by=OWNER, now=T1)
    store.set_visibility("report", "private", [FRIEND])
    server = serve()
    assert opens(server, OWNER) == opens(server, FRIEND) == (200, 200, 200)
    assert opens(server, OTHER) == (403, 403, 403)
    status, _, body = request(server, "/report/", who=OTHER)
    assert b"open to its owner and the people they share it with only" in body
    # The listed person sees it everywhere the owner does; others nowhere.
    assert '<a href="/report/">' in request(server, "/", who=FRIEND)[2].decode()
    assert '<a href="/report/">' not in request(server, "/", who=OTHER)[2].decode()
    listed = json.loads(request(server, "/_api/pages", who=FRIEND)[2])["pages"]
    assert [(p["name"], p["people"]) for p in listed] == [("report", [FRIEND])]
    assert json.loads(request(server, "/_api/pages", who=OTHER)[2])["pages"] == []
    overview = json.loads(request(server, "/_api/overview", who=FRIEND)[2])
    assert [r["name"] for r in overview["reports"]] == ["report"]
    for path in ("/report/_info", "/_api/pages/report/info", "/_api/pages/report/comments"):
        assert request(server, path, who=FRIEND)[0] == 200, path
        assert request(server, path, who=OTHER)[0] == 403, path
    facts = json.loads(request(server, "/_api/pages/report", who=FRIEND)[2])
    assert (facts["people"], facts["role"]) == ([FRIEND], "viewer")

    # Only the owner shares, and sets the whole list.
    status, answer = post(server, {"visibility": "private", "people": [OTHER]}, who=FRIEND)
    assert (status, answer) == (403, {"error": "only the owner can change this"})
    status, answer = post(server, {"visibility": "private", "people": [OTHER, FRIEND]})
    assert (status, answer["people"]) == (200, [FRIEND, OTHER])
    assert opens(server, OTHER) == (200, 200, 200)
    assert post(server, {"visibility": "ontic", "people": [FRIEND]})[0] == 400
    status, answer = post(server, {"visibility": "private", "people": ["x@gmail.com"]})
    assert status == 400 and "@onticlabs.io" in answer["error"]
    assert post(server, {"visibility": "private", "people": FRIEND})[0] == 400
    assert store.access("report") == ("private", (FRIEND, OTHER))
    assert post(server, {"visibility": "ontic"})[0] == 200  # another level drops the list
    assert store.access("report") == ("ontic", ())
    assert post(server, {"visibility": "private"})[1]["people"] == []
    assert opens(server, FRIEND) == (403, 403, 403)


def test_cli_direct(cli_env, site, capsys, monkeypatch):
    monkeypatch.setenv("ONTIC_PAGES_EMAIL", OWNER)
    store = Store(cli_env, "test-bucket")
    main(["publish", str(site), "--name", "report", "--visibility", "private",
          "--with", FRIEND.upper()])  # fmt: skip
    assert f"private: only {OWNER}, {FRIEND} can open it" in capsys.readouterr().out
    assert store.access("report") == ("private", (FRIEND,))
    main(["publish", str(site), "--name", "report"])  # no level: level and people stay
    assert store.access("report") == ("private", (FRIEND,))
    main(["share", "report", "private", "--with", OTHER, "--with", FRIEND])
    assert f"only {OWNER}, {FRIEND}, {OTHER} can open it" in capsys.readouterr().out
    main(["list"])
    assert f"shared with {FRIEND}, {OTHER}" in capsys.readouterr().out
    main(["info", "report"])
    assert f"visibility   private, shared with {FRIEND}, {OTHER}" in capsys.readouterr().out
    for argv, error in [
        (["share", "report", "ontic", "--with", FRIEND], "--with shares a private page"),
        (["publish", str(site), "--name", "report", "--with", FRIEND], "--with shares"),
        (["share", "report", "private", "--with", "x@gmail.com"], "bad email"),
        (["share", "report", "private", "--with", "f@example.org"], "bad email"),  # --direct
    ]:
        with pytest.raises(SystemExit, match=error):
            main(argv)
    assert store.access("report") == ("private", (FRIEND, OTHER))
    main(["share", "report", "private"])  # no --with: only the owner again
    assert store.access("report") == ("private", ())


def test_cli_through_the_gateway(local, gateway_env, store, uploads, site, capsys):
    srv = local()
    gateway_env(srv, OWNER)
    main(["publish", str(site), "--name", "report", "--visibility", "private", "--with", FRIEND])
    assert f"private: only {OWNER}, {FRIEND} can open it" in capsys.readouterr().out
    assert store.access("report") == ("private", (FRIEND,))
    main(["share", "report", "private", "--with", OTHER])
    assert f"only {OWNER}, {OTHER} can open it" in capsys.readouterr().out
    assert store.access("report") == ("private", (OTHER,))
    main(["info", "report"])
    assert f"private, shared with {OTHER}" in capsys.readouterr().out
    main(["list", "--name", "report"])
    assert capsys.readouterr().out.startswith(f"visibility: private, shared with {OTHER}")
    gateway_env(srv, OTHER)
    main(["list"])
    assert f"shared with {OTHER}" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="only the owner"):
        main(["share", "report", "private", "--with", OTHER, "--with", FRIEND])


def test_cli_against_a_gateway_without_people(
    local, gateway_env, store, uploads, site, monkeypatch
):
    """A gateway from before people drops them and never answers them: say so, not success."""
    srv = local()
    gateway_env(srv, OWNER)
    main(["publish", str(site), "--name", "report"])
    real = remote.Api.json

    def old(self, method, path, body=None):
        if isinstance(body, dict):
            body = {k: v for k, v in body.items() if k != "people"}
        answer = real(self, method, path, body)
        answer.pop("people", None)
        return answer

    monkeypatch.setattr(remote.Api, "json", old)
    with pytest.raises(SystemExit, match="does not support sharing with people yet.*unchanged"):
        main(["share", "report", "private", "--with", FRIEND])
    assert store.access("report") == ("ontic", ())  # asked before changing anything
    with pytest.raises(SystemExit, match="does not support sharing.*private to you alone"):
        main(["publish", str(site), "--name", "report", "--visibility", "private",
              "--with", FRIEND])  # fmt: skip
    assert store.access("report") == ("private", ())
    main(["share", "report", "ontic"])  # without people it works as before
    assert store.access("report") == ("ontic", ())


def test_cli_leaves_the_domain_to_the_gateway(local, gateway_env, store, uploads, site):
    """Through a gateway with another --email-domain, its domain counts, not onticlabs.io."""
    srv = local(email_domain="example.org")
    gateway_env(srv, "boss@example.org")
    main(["publish", str(site), "--name", "report", "--visibility", "private",
          "--with", "f@example.org"])  # fmt: skip
    assert store.access("report") == ("private", ("f@example.org",))
    with pytest.raises(SystemExit, match="bad email.*@example.org"):
        main(["share", "report", "private", "--with", FRIEND])
    with pytest.raises(SystemExit, match="bad email"):  # not an email at all: refused here
        main(["share", "report", "private", "--with", "not-an-email"])
    assert store.access("report") == ("private", ("f@example.org",))
