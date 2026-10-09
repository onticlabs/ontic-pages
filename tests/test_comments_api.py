"""The comments API on the gateway: who may read and write, the write checks, the limits."""

import json
from datetime import UTC, datetime

import pytest
from helpers import ORIGIN, SECRET, TEAM, request

from ontic_pages.comments import BODY_LIMIT
from ontic_pages.publish import publish
from ontic_pages.tokens import sign

T1 = datetime(2026, 10, 7, 15, 30, tzinfo=UTC)
T2 = datetime(2026, 10, 8, 9, 0, tzinfo=UTC)
OWNER = "owner@onticlabs.io"
OTHER = "other.person@onticlabs.io"
OUTSIDER = "someone@gmail.com"
ANCHOR = {"path": "/", "selector": "p", "fx": 0.25, "fy": 0.5, "snippet": "x", "x": 1, "y": 2}
BAR = {"Content-Type": "application/json", "Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"}
WIDE = "漢"  # three bytes in UTF-8


@pytest.fixture
def report(store, site):
    """report: two versions by OWNER, the second current."""
    first = publish(store, site, "report", "first", published_by=OWNER, now=T1)["version"]
    second = publish(store, site, "report", "second", published_by=OWNER, now=T2)["version"]
    return first, second


def saved(s3) -> dict:
    return json.loads(s3.objects[("test-bucket", "report/comments.json")][0])


def api(srv, path, body=None, who=TEAM, headers=None, host=None):
    """(status, JSON) from the bar: a cookie and the apex's own headers on writes."""
    kwargs = {"host": host} if host else {}
    data = None if body is None else json.dumps(body).encode()
    status, _, out = request(
        srv, "/_api/pages/report/comments" + path, who=who,
        headers={**(BAR if body is not None else {}), **(headers or {})},
        method="POST" if body is not None else "GET", body=data, **kwargs,
    )  # fmt: skip
    return status, json.loads(out) if out.startswith(b"{") else out


def test_api_flow(serve, store, s3, report):
    srv = serve()
    v1, v2 = report
    assert api(srv, "") == (200, {"name": "report", "current": v2, "open": 0, "threads": []})
    status, answer = api(srv, "", {"anchor": ANCHOR, "body": " Row 3 \r\n looks off "})
    assert status == 201
    thread = answer["thread"]
    tid = thread["id"]
    assert thread["version"] == v2  # no version given: the current one
    assert thread["comments"][0]["body"] == "Row 3 \n looks off"
    assert thread["comments"][0]["mine"] is True and thread["created_by"] == TEAM
    assert thread["created_by_name"] == "Tester"

    # On an older version, said so.
    status, answer = api(srv, "", {"anchor": ANCHOR, "version": v1, "body": "old"}, who=OTHER)
    assert status == 201 and answer["thread"]["version"] == v1
    assert api(srv, "", {"anchor": ANCHOR, "version": "20990101T000000Z", "body": "x"})[0] == 400

    status, answer = api(srv, f"/{tid}/reply", {"body": "Fixed"}, who=OWNER)
    assert status == 200 and [c["mine"] for c in answer["thread"]["comments"]] == [False, True]
    status, answer = api(srv, f"/{tid}/resolve", {"resolved": True}, who=OWNER)
    assert status == 200 and answer["thread"]["resolved"] is True
    assert answer["thread"]["resolved_by_name"] == "Owner"
    assert api(srv, f"/{tid}/resolve", {"resolved": "yes"})[0] == 400

    status, listed = api(srv, "", who=OTHER)
    assert status == 200 and listed["open"] == 1 and len(listed["threads"]) == 2
    assert {t["id"]: t["resolved"] for t in listed["threads"]}[tid] is True

    # Deleting: own comments only, then a tombstone.
    first = thread["comments"][0]["id"]
    status, answer = api(srv, f"/{tid}/{first}/delete", {}, who=OWNER)
    assert (status, answer["error"]) == (403, "only its author can delete a comment")
    status, answer = api(srv, f"/{tid}/{first}/delete", {})
    assert status == 200 and answer["thread"]["comments"][0]["deleted"] is True
    assert answer["thread"]["comments"][0]["body"] == ""
    assert saved(s3)["threads"][0]["comments"][0]["deleted"] is True

    assert api(srv, f"/{'f' * 16}/reply", {"body": "x"})[0] == 404
    assert api(srv, f"/{tid}/reply", {"body": "   "})[0] == 400
    assert api(srv, f"/{tid}/reply", {"body": "x" * (BODY_LIMIT + 1)})[0] == 400
    assert api(srv, "/xyz/reply", {"body": "x"})[0] == 404  # not an id: no such route
    assert "delete_object" not in s3.calls


def test_api_access(serve, store, report):
    srv = serve()
    assert api(srv, "", {"anchor": ANCHOR, "body": "hi"})[0] == 201
    assert api(srv, "", who=OUTSIDER)[0] == 403
    assert api(srv, "", {"anchor": ANCHOR, "body": "hi"}, who=OUTSIDER)[0] == 403
    assert api(srv, "", who=None)[0] == 401
    # A public page: anyone may open it, but signed out there are no comments to read or add.
    store.set_visibility("report", "public")
    status, answer = api(srv, "", who=None)
    assert status == 401 and "@" not in json.dumps(answer)
    assert api(srv, "", {"anchor": ANCHOR, "body": "hi"}, who=None)[0] == 401
    assert api(srv, "", who=OUTSIDER)[0] == 200  # signed in and may open it
    # Private: only the owner.
    store.set_visibility("report", "private")
    assert api(srv, "")[0] == 403
    assert api(srv, "", who=OWNER)[0] == 200
    assert request(srv, "/_api/pages/ghost/comments")[0] == 404


def test_api_write_checks(serve, store, report):
    srv = serve()
    body = {"anchor": ANCHOR, "body": "hi"}
    page_host = f"report.{ORIGIN.removeprefix('https://')}"
    # From a page's own scripts (same-site, the viewer's cookie) or elsewhere: refused.
    for headers in ({"Sec-Fetch-Site": "same-site"}, {"Origin": f"https://{page_host}"},
                    {"Content-Type": "text/plain"}):  # fmt: skip
        assert api(srv, "", body, headers=headers)[0] in (403, 415), headers
    assert api(srv, "", body, host=page_host)[0] == 405
    # Reads are for the bar and the command line, not a page's scripts.
    assert api(srv, "", headers={"Sec-Fetch-Site": "same-site"})[0] == 403
    assert api(srv, "", headers={"Sec-Fetch-Site": "same-origin"})[0] == 200
    # Bodies up to 32 KB (4000 characters of any script), never more.
    assert api(srv, "", {"anchor": ANCHOR, "body": WIDE * BODY_LIMIT})[0] == 201
    assert api(srv, "", {"anchor": ANCHOR, "body": "x" * 40000})[0] == 413
    assert store.read_text(store.key("report", "comments.json")).count('"author"') == 1


def test_api_rate_limit(serve, report):
    srv = serve()
    status, answer = api(srv, "", {"anchor": ANCHOR, "body": "1"})
    tid = answer["thread"]["id"]
    for _ in range(19):
        assert api(srv, f"/{tid}/reply", {"body": "x"})[0] == 200
    status, answer = api(srv, f"/{tid}/reply", {"body": "x"})
    assert status == 429 and "wait" in answer["error"]
    assert api(srv, f"/{tid}/reply", {"body": "x"}, who=OWNER)[0] == 200  # their own limit


def test_api_with_a_token(local, store, report):
    srv = local()
    host = srv.url.removeprefix("http://")
    token = {"Authorization": f"Bearer {sign(SECRET, OWNER)}", "Content-Type": "application/json"}
    body = json.dumps({"anchor": ANCHOR, "body": "from the command line"}).encode()
    status, _, out = request(srv, "/_api/pages/report/comments", host=host, who=None,
                             headers=token, method="POST", body=body)  # fmt: skip
    assert status == 201 and json.loads(out)["thread"]["created_by"] == OWNER
    status, _, out = request(srv, "/_api/pages/report/comments", host=host, who=None,
                             headers=token)  # fmt: skip
    assert status == 200 and json.loads(out)["threads"][0]["comments"][0]["mine"] is True
    # Never from a browser.
    status, _, _ = request(srv, "/_api/pages/report/comments", host=host, who=None,
                           headers={**token, "Origin": srv.url})  # fmt: skip
    assert status == 403
