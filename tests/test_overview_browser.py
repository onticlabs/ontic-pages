"""The overview in a browser while its reports come: uv run --with playwright pytest -q
tests/test_overview_browser.py. Uses installed Chromium (CHROMIUM_PATH overrides) and a real
gateway on the fake store; a page's state read is held back to see the rows come one by one."""

import os
import shutil
import threading
from datetime import UTC, datetime

import pytest
from botocore.exceptions import ClientError
from helpers import cookie_identity, stop

from ontic_pages.gateway import Site, make_server
from ontic_pages.publish import publish

playwright = pytest.importorskip("playwright.sync_api", reason="run with uv run --with playwright")
CHROMIUM = os.environ.get("CHROMIUM_PATH") or shutil.which("chromium")
pytestmark = pytest.mark.skipif(not CHROMIUM, reason="needs Chromium (or CHROMIUM_PATH)")
OWNER = "owner@onticlabs.io"
T1 = datetime(2026, 10, 14, 1, tzinfo=UTC)


@pytest.fixture
def overview(store, site, monkeypatch):
    """(browser page, apex origin, hold): hold[name] is an Event a read of that page's state
    waits for; hold["fail"] is the names whose read fails."""
    for name in ("fast-report", "slow-report"):
        publish(store, site, name, published_by=OWNER, now=T1)
    hold: dict = {"fail": set()}
    real = store.current

    def current(name):
        if name in hold["fail"]:
            raise ClientError({"Error": {"Code": "InternalError"}}, "GetObject")
        if name in hold:
            assert hold[name].wait(10)
        return real(name)

    monkeypatch.setattr(store, "current", current)
    server = make_server(store, "127.0.0.1", 0)
    port = server.server_port
    server.server_close()
    origin = f"http://pages.test:{port}"
    server = make_server(
        store, "127.0.0.1", port, site=Site(origin), identity=cookie_identity, ttl=0
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=CHROMIUM,
            args=[
                "--no-sandbox",
                "--disable-gpu",
                "--no-proxy-server",
                "--host-resolver-rules=MAP pages.test 127.0.0.1, MAP *.pages.test 127.0.0.1",
                f"--unsafely-treat-insecure-origin-as-secure={origin}",
            ],
        )
        context = browser.new_context()
        context.add_cookies([{"name": "who", "value": OWNER, "url": origin}])
        page = context.new_page()
        try:
            yield page, origin, hold
        finally:
            for event in hold.values():
                if isinstance(event, threading.Event):
                    event.set()
            browser.close()
            stop(server)


def note(page):
    return page.locator(".head .loadnote")


def test_rows_show_as_they_come(overview):
    page, origin, hold = overview
    hold["slow-report"] = threading.Event()
    page.goto(origin + "/")
    page.get_by_text("fast-report").wait_for()
    assert note(page).inner_text() == "Loading, 1 report so far"
    assert page.get_by_text("slow-report").count() == 0
    # Typing in search while rows come: the text and the caret stay where they were.
    search = page.locator("#q")
    search.click()
    search.press_sequentially("report")
    page.evaluate("document.getElementById('q').setSelectionRange(2, 2)")
    hold["slow-report"].set()
    page.get_by_text("slow-report").wait_for()
    note(page).wait_for(state="detached")
    assert page.evaluate("[document.activeElement.id, document.activeElement.selectionStart]") == [
        "q",
        2,
    ]
    assert search.input_value() == "report"


def test_a_failed_read_says_so_and_retry_completes(overview):
    page, origin, hold = overview
    hold["fail"].add("slow-report")
    page.goto(origin + "/")
    page.get_by_text("Some reports may be missing: store error.").wait_for()
    assert page.get_by_text("fast-report").count() == 1
    hold["fail"].clear()
    note(page).get_by_role("button", name="Retry").click()
    page.get_by_text("slow-report").wait_for()
    note(page).wait_for(state="detached")


def test_nothing_read_yet_shows_the_skeleton(overview):
    page, origin, hold = overview
    hold["fast-report"] = threading.Event()
    hold["slow-report"] = threading.Event()
    page.goto(origin + "/")
    note(page).wait_for()
    assert note(page).inner_text() == "Loading reports"
    assert page.locator(".skeleton i").count() == 8
    hold["fast-report"].set()
    hold["slow-report"].set()
    page.get_by_text("slow-report").wait_for()
    assert page.locator(".skeleton").count() == 0


def test_tags_added_across_a_refresh_both_stay(overview, store):
    page, origin, hold = overview
    page.goto(origin + "/")
    page.get_by_text("slow-report").wait_for()
    page.get_by_role("tab", name="Exploratory").click()  # the view that shows tags
    # A focus refresh (its 30 s pause skipped), held back until the tag editor is open.
    hold["fast-report"] = threading.Event()
    page.evaluate("(() => { const now = Date.now; Date.now = () => now() + 60000; })()")
    page.evaluate("window.dispatchEvent(new Event('focus'))")
    row = page.locator("tr", has_text="slow-report")
    tags = row.locator("td").nth(page.locator("th").all_inner_texts().index("Tags"))
    tags.click()
    tag = page.locator("#cell-input")
    tag.fill("alpha")
    hold["fast-report"].set()  # the refresh completes while the editor is open
    page.wait_for_timeout(500)  # the refresh's last read is done: its rows are in, not drawn
    saved = lambda r: r.url.endswith("/labels") and r.request.method == "POST"  # noqa: E731
    with page.expect_response(saved):
        tag.press("Enter")
    tag.fill("beta")
    with page.expect_response(saved):
        tag.press("Enter")
    tag.press("Escape")
    assert tags.locator(".sel").all_inner_texts() == ["alpha", "beta"]
    assert store.labels("slow-report")["tags"] == ["alpha", "beta"]
