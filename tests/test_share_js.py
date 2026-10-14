"""The Share panel's people (bar.js) in node, with the fake DOM of test_edit_js: shown on a private
page, edited and saved by the owner only, typed text kept when the gateway refuses it."""

import pytest
from test_edit_js import NODE, run, served

pytestmark = pytest.mark.skipif(not NODE, reason="needs node")

SHARE = r"""
const PAGE = { name: "report", content_origin: CONTENT, current: "v1", role: ROLE,
  visibility: "private", people: PEOPLE, published_by: "owner@onticlabs.io",
  email_domain: "onticlabs.io", versions: [{ version: "v1", published_at: "", description: "" }] };
const facts = { page: PAGE, view: { path: "/", version: null } };
const frame = E("iframe", { id: "frame" });
frame.contentWindow = { postMessage() {} };
const access = E("select", { id: "s-access" });
access.options = [];
access.selectedIndex = 0;
const field = E("input", { id: "s-people" });
field.value = "";
const box = E("div", { id: "s-people-box" }), save = E("button", { id: "s-people-save" });
box.hidden = save.hidden = true;
const ids = ["m-by", "m-owner", "m-time", "m-desc", "m-versions", "old", "s-note", "s-explain",
  "s-owner", "s-error", "title-btn", "title-menu", "info-btn", "info-panel", "share-btn",
  "share-panel", "m-raw", "slow", "retry"];
const stage = E("main", { id: "stage" }, [frame,
  E("div", { id: "status" }, [E("div", { class: "spinner" })])]);
const bar = E("header", { class: "bar" }, [access, box, field, save,
  ...ids.map((id) => E("div", { id }))]);
const body = E("body", {}, [bar, stage]);
const byId = (id) => (id === "ontic-facts" ? { textContent: JSON.stringify(facts) }
  : body.querySelectorAll("*").find((n) => n.id === id) || null);
const document = target({ body, getElementById: byId, visibilityState: "visible",
  createElement: (t) => new El(t), querySelector: (s) => body.querySelector(s),
  querySelectorAll: (s) => body.querySelectorAll(s) });
const window = target({});
const fetches = [], answers = [];
function fetch(url, options) {
  fetches.push([url, options.method, JSON.parse(options.body)]);
  const a = answers.shift();
  const response = { ok: a.ok, status: a.status, json: () => Promise.resolve(a.body) };
  return a.gate ? a.gate.then(() => response) : Promise.resolve(response);
}
const location = { origin: APEX, href: APEX + "/report/", hash: "", assign() {} };
vm.runInNewContext(SOURCE, { window, document, location, history: { replaceState() {} }, URL,
  fetch, JSON, Date, setTimeout: () => 0, clearTimeout() {}, setInterval: () => 0 });
fire(document, "DOMContentLoaded");
const error = byId("s-error");
(async () => {
  const out = { first: [box.hidden, field.value, field.readOnly, save.hidden] };
  if (RACE) {
    // Save [a, b], take b off and save again before the first answer: the second is sent only
    // after it, so b cannot come back; the select stays disabled meanwhile.
    let release;
    const both = Object.assign({}, PAGE, { people: ["a@onticlabs.io", "b@onticlabs.io"] });
    answers.push({ ok: true, status: 200, body: both, gate: new Promise((r) => (release = r)) });
    answers.push({ ok: true, status: 200, body: Object.assign({}, PAGE,
      { people: ["a@onticlabs.io"] }) });
    field.value = "a@onticlabs.io, b@onticlabs.io";
    fire(field, "input");
    save.click();
    field.value = "a@onticlabs.io";
    fire(field, "input");
    fire(field, "keydown", { key: "Enter" });
    for (let i = 0; i < 5; i++) await tick();
    out.running = [fetches.map((f) => f[2].people), access.disabled];
    release();
    for (let i = 0; i < 10; i++) await tick();
    out.done = [fetches.map((f) => f[2].people), field.value, access.disabled];
    for (let i = 0; i < 10; i++) await tick();
    out.calls = fetches.length;
  } else if (ROLE !== "owner") {
    fire(field, "keydown", { key: "Enter" });
    out.enter = fetches.length;
  } else {
    field.value = "B@onticlabs.io, x@gmail.com;  ";
    fire(field, "input");
    answers.push({ ok: false, status: 400, body: { error: "bad email <b>'x@gmail.com'</b>" } });
    save.click();
    for (let i = 0; i < 5; i++) await tick();
    out.refused = [fetches.slice(), field.value, error.textContent, error.hidden];
    fetches.length = 0;
    field.value = "b@onticlabs.io";
    answers.push({ ok: true, status: 200, body: Object.assign({}, PAGE,
      { people: ["a@onticlabs.io", "b@onticlabs.io"] }) });
    fire(field, "keydown", { key: "Enter" });
    for (let i = 0; i < 5; i++) await tick();
    out.saved = [fetches.slice(), field.value, error.hidden];
  }
  console.log(JSON.stringify(out));
})();
"""


def share(role: str, people: list[str], race: bool = False) -> dict:
    return run(SHARE, served("bar.js"), ROLE=role, PEOPLE=people, RACE=race)


def test_owner_edits_the_people():
    out = share("owner", ["a@onticlabs.io"])
    assert out["first"] == [False, "a@onticlabs.io", False, False]
    url = "/_api/pages/report/visibility"
    sent = {"visibility": "private", "people": ["B@onticlabs.io", "x@gmail.com"]}
    # Refused: the error as text, and what was typed stays to be fixed.
    assert out["refused"] == [
        [[url, "POST", sent]], "B@onticlabs.io, x@gmail.com;  ",
        "bad email <b>'x@gmail.com'</b>", False,
    ]  # fmt: skip
    # Saved (Enter): the field shows the list as the gateway keeps it.
    sent = {"visibility": "private", "people": ["b@onticlabs.io"]}
    assert out["saved"] == [[[url, "POST", sent]], "a@onticlabs.io, b@onticlabs.io", True]


def test_one_change_at_a_time():
    out = share("owner", ["a@onticlabs.io", "b@onticlabs.io"], race=True)
    assert out["running"] == [[["a@onticlabs.io", "b@onticlabs.io"]], True]
    # The second save goes out once, after the first answer, with what was typed last.
    sent = [["a@onticlabs.io", "b@onticlabs.io"], ["a@onticlabs.io"]]
    assert out["done"] == [sent, "a@onticlabs.io", False] and out["calls"] == 2


def test_people_see_the_list_read_only():
    out = share("viewer", ["a@onticlabs.io", "b@onticlabs.io"])
    assert out["first"] == [False, "a@onticlabs.io, b@onticlabs.io", True, True]
    assert out["enter"] == 0  # Enter saves nothing for them
    assert share("viewer", [])["first"][0] is True  # nobody listed: nothing to show
