"""Text edited in the bar: finding it in the source, and saving it as a new version."""

import json
from datetime import UTC, datetime

import pytest
from helpers import ORIGIN, request

from ontic_pages import edits
from ontic_pages.edits import STALE, check, patch, save, text_spans
from ontic_pages.publish import publish
from ontic_pages.uploads import Refused, Uploads

T1 = datetime(2026, 10, 7, 15, 30, tzinfo=UTC)
OWNER = "owner@onticlabs.io"
OTHER = "other@onticlabs.io"
PAGE = (
    "<!doctype html><html><head><title>Results</title>\r\n"
    "<style>h1::after { content: 'Results' }</style></head>\r\n"
    "<body><h1>Results</h1>\r\n"
    "<p>Tom &amp; Jerry&nbsp;are <b>friends</b>, caf&#233; &eacute;t&#xE9;</p>\r\n"
    "<ul><li>Same</li><li>Same</li><li>Results, and more</li></ul>\r\n"
    "<!-- Unique comment --><pre>line one\r\nline two</pre>\r\n"
    '<script>var label = "Unique script";</script></body></html>'
)


def change(before, after):
    return {"before": before, "after": after}


# --- finding text in the source -----------------------------------------------------------


def test_text_spans_leave_out_tags_scripts_styles_and_the_title():
    texts = [PAGE[a:b] for a, b in text_spans(PAGE)]
    assert "Results" in texts and "Same" in texts
    assert "Tom &amp; Jerry&nbsp;are " in texts  # character references stay in their text
    assert not any("Unique" in t for t in texts)  # not in comments or scripts
    assert not any("content:" in t for t in texts)
    assert texts.count("Results") == 1  # the title is not page text


def test_patch_exact_text():
    out = patch(PAGE, [change("Results", "Findings")])
    assert "<h1>Findings</h1>" in out
    assert "<title>Results</title>" in out and "Results, and more" in out  # the rest unchanged
    assert out.replace("<h1>Findings</h1>", "<h1>Results</h1>") == PAGE


def test_patch_text_written_with_references():
    out = patch(PAGE, [change("Tom & Jerry are ", "Tom & Jerry were ")])
    assert "<p>Tom &amp; Jerry&nbsp;were <b>" in out  # only the changed part is replaced
    out = patch(PAGE, [change(", café été", ", café été <3")])
    assert "caf&#233; &eacute;t&#xE9; &lt;3</p>" in out
    out = patch(PAGE, [change("friends", "a & b <i>")])
    assert "<b>a &amp; b &lt;i&gt;</b>" in out  # the new text is escaped


def test_patch_line_breaks():
    out = patch(PAGE, [change("line one\nline two", "line one\nline 2")])
    assert "<pre>line one\r\nline 2</pre>" in out  # the source keeps its CR LF


def test_patch_missing_and_ambiguous_refuse_everything():
    with pytest.raises(Refused) as err:
        patch(PAGE, [change("Results", "Findings"), change("Not here", "x"), change("Same", "x")])
    assert err.value.status == 422
    message = err.value.message
    assert message.startswith("Nothing saved: 2 of 3 changes could not be placed.")
    assert '"Not here" is not in the HTML source (a script may write it)' in message
    assert '"Same" is in the page 2 times; cannot tell which one' in message
    with pytest.raises(Refused, match="not in the HTML source"):
        patch(PAGE, [change("Unique script", "x")])  # a script's text is not page text
    with pytest.raises(Refused, match="2 times"):
        patch("<p>a b</p><p>c b d</p>", [change("b", "x")])


def test_patch_whole_element_wins():
    # "Results" also starts the third item, but one element holds exactly that text.
    out = patch(PAGE, [change("Results, and more", "More")])
    assert "<li>More</li>" in out and "<h1>Results</h1>" in out


def test_patch_overlapping_changes():
    with pytest.raises(Refused, match="overlaps"):
        patch("<p>one two three</p>", [change("one two", "1 2"), change("two three", "2 3")])
    out = patch("<p>one</p><p>two</p>", [change("two", "2"), change("one", "1")])
    assert out == "<p>1</p><p>2</p>"


V = "20261007T153000Z"
AB = [change("a", "b")]


@pytest.mark.parametrize(
    "body, error",
    [
        ([], "send {version"),
        ({"path": "/", "changes": AB}, "version"),
        ({"version": "x", "path": "/", "changes": AB}, "version"),
        ({"version": V, "path": "index.html", "changes": AB}, "path"),
        ({"version": V, "path": "/", "changes": []}, "changes"),
        ({"version": V, "path": "/", "changes": "x"}, "changes"),
        ({"version": V, "path": "/", "changes": [{"before": "a"}]}, "each"),
        ({"version": V, "path": "/", "changes": [change("", "b")]}, "each"),
        ({"version": V, "path": "/", "changes": [change("a", "a")]}, "nothing"),
        ({"version": V, "path": f"/_v/{V}/", "changes": AB}, "current version"),
        ({"version": V, "path": "/style.css", "changes": AB}, "only HTML"),
        ({"version": V, "path": "/../x.html", "changes": AB}, "bad file path"),
        ({"version": V, "path": "/", "changes": [change("a", "b" * 20001)]}, "at most"),
    ],
)
def test_check_refuses(body, error):
    with pytest.raises(Refused, match=error):
        check(body)


def test_check_paths_and_changes():
    v = "20261007T153000Z"
    many = [change(f"a{i}", "b") for i in range(edits.MAX_CHANGES + 1)]
    with pytest.raises(Refused, match="1 to 500"):
        check({"version": v, "path": "/", "changes": many})
    body = {"version": v, "path": "/docs/", "changes": [change("a\r\nb", "c"), change("x", "x")]}
    assert check(body) == (v, "docs/index.html", [change("a\nb", "c")])
    assert check({**body, "path": "/"})[1] == "index.html"
    assert check({**body, "path": "/my%20page.html?x=1#y"})[1] == "my page.html"


# --- saving a new version -----------------------------------------------------------------


@pytest.fixture
def page(store, site):
    """report: OWNER's page with PAGE as index.html, meta and a description."""
    (site / "index.html").write_text(PAGE, newline="")
    return publish(
        store, site, "report", "first", {"model": "abc"}, published_by=OWNER, now=T1
    )  # fmt: skip


def body(page, *changes, path="/"):
    return {"version": page["version"], "path": path, "changes": list(changes)}


def test_save_writes_a_new_version(store, s3, page):
    old = page["version"]
    new = save(store, "report", OWNER, body(page, change("Results", "Findings")))
    assert store.current("report") == new["version"] != old
    assert store.meta("report", new["version"]) == new
    assert new["published_by"] == OWNER
    assert (new["description"], new["files"], new["git"]) == ("first", 6, page["git"])
    assert new["meta"] == {"model": "abc", "edited_from": old}
    # The edited file, patched; the others copied inside the bucket, with their types.
    data = s3.objects[("test-bucket", f"report/{new['version']}/index.html")]
    patched = PAGE.replace("<h1>Results", "<h1>Findings").encode()
    assert data == (patched, "text/html; charset=utf-8")
    for path in ("style.css", "app.js", "data.json", "img/dot.png", "docs/index.html"):
        copied = s3.objects[("test-bucket", f"report/{new['version']}/{path}")]
        assert copied == s3.objects[("test-bucket", f"report/{old}/{path}")]
    assert s3.calls.count("copy_object") == 5
    # Nothing of the old version changed.
    assert s3.objects[("test-bucket", f"report/{old}/index.html")][0] == PAGE.encode()


def test_save_another_file_and_again(store, s3, page):
    first = save(store, "report", OWNER, body(page, change("docs", "Docs!"), path="/docs/"))
    assert s3.objects[("test-bucket", f"report/{first['version']}/docs/index.html")][0] == (
        b"<p>Docs!</p>"
    )
    # An edit of an edited version keeps the meta and points at the version it came from.
    second = save(store, "report", OWNER, body(first, change("Results", "Findings")))
    assert second["meta"] == {"model": "abc", "edited_from": first["version"]}
    assert len(store.versions("report")) == 3


def test_save_refuses_a_stale_version(store, site, page):
    newer = publish(store, site, "report", "newer", published_by=OWNER)
    with pytest.raises(Refused) as err:
        save(store, "report", OWNER, body(page, change("Results", "Findings")))
    assert (err.value.status, err.value.message) == (409, STALE)
    assert store.current("report") == newer["version"] and len(store.versions("report")) == 2


def test_save_owner_only(store, page):
    with pytest.raises(Refused, match="only the owner") as err:
        save(store, "report", OTHER, body(page, change("Results", "Findings")))
    assert err.value.status == 403
    assert store.versions("report") == [page["version"]]


def test_save_refusals_write_nothing(store, s3, page, monkeypatch):
    before = dict(s3.objects)
    with pytest.raises(Refused, match="is in the page 2 times"):
        save(store, "report", OWNER, body(page, change("Results", "x"), change("Same", "y")))
    with pytest.raises(Refused, match="not in version"):
        save(store, "report", OWNER, body(page, change("a", "b"), path="/nope.html"))
    with pytest.raises(Refused, match="no page named"):
        save(store, "ghost", OWNER, body(page, change("a", "b")))
    s3.objects[("test-bucket", f"report/{page['version']}/latin.html")] = (b"caf\xe9", "text/html")
    with pytest.raises(Refused, match="not UTF-8"):
        save(store, "report", OWNER, body(page, change("a", "b"), path="/latin.html"))
    monkeypatch.setattr(edits, "MAX_HTML", 10)
    with pytest.raises(Refused, match="over 0 MB") as err:
        save(store, "report", OWNER, body(page, change("Results", "x")))
    assert err.value.status == 413
    del s3.objects[("test-bucket", f"report/{page['version']}/latin.html")]
    assert s3.objects == before


def test_save_reserves_its_version(store, page):
    uploads = Uploads(store)
    taken = uploads.reserve("report")
    up, _ = uploads.start("report", OWNER, {"files": [{"path": "index.html", "size": 1}]})
    assert up.version != taken  # a publish never shares a version folder with an edit
    new = save(store, "report", OWNER, body(page, change("Results", "x")), uploads)
    assert new["version"] not in (taken, up.version)
    assert uploads.reserved == {("report", taken)}  # its own reservation is released


# --- through the gateway ------------------------------------------------------------------

WRITE = {"Content-Type": "application/json", "Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"}


def post(server, data, who=OWNER, headers=None, name="report"):
    raw = data if isinstance(data, bytes) else json.dumps(data).encode()
    status, _, out = request(
        server, f"/_api/pages/{name}/edits", who=who, method="POST", body=raw,
        headers={**WRITE, **(headers or {})},
    )  # fmt: skip
    return status, json.loads(out)


def test_gateway_saves_edits(serve, store, page):
    server = serve(ttl=60)
    assert request(server, "/_api/pages/report", who=OWNER)[0] == 200  # remembered for 60 s
    status, answer = post(server, body(page, change("Results", "Findings")))
    assert status == 200
    new = answer["version"]
    assert store.current("report") == new and answer["page"]["current"] == new
    assert answer["page"]["role"] == "owner" and answer["page"]["versions"][0]["version"] == new
    assert store.meta("report", new)["meta"]["edited_from"] == page["version"]
    # The cache forgot: the new version shows at once.
    assert json.loads(request(server, "/_api/pages/report")[2])["current"] == new
    # The edit was made on the version before: refused now.
    status, answer = post(server, body(page, change("Findings", "Results")))
    assert (status, answer) == (409, {"error": STALE})


def test_gateway_edits_owner_only_and_from_the_bar(serve, store, page):
    server = serve()
    data = body(page, change("Results", "Findings"))
    status, answer = post(server, data, who=OTHER)
    assert (status, answer["error"]) == (403, "only the owner can edit this page")
    assert post(server, data, who=None)[0] == 401
    assert post(server, data, headers={"Sec-Fetch-Site": "same-site"})[0] == 403
    assert post(server, data, headers={"Origin": "https://report.pages.test"})[0] == 403
    assert post(server, data, name="ghost")[0] == 404
    assert post(server, {"version": page["version"]})[0] == 400
    status, answer = post(server, body(page, change("Same", "x")))
    assert status == 422 and "2 times" in answer["error"]
    assert store.versions("report") == [page["version"]]


def test_gateway_edits_body_limit(serve, store, page):
    server = serve()
    big = body(page, change("Results", "Findings " + "x" * 10_000))
    assert post(server, big)[0] == 200  # over the 4 KB of other writes, under Caddy's 64 KB
    huge = body(page, *[change(f"t{i}", "y" * 9_000) for i in range(8)])
    assert post(server, huge)[0] == 413
