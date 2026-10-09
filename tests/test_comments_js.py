"""The comment scripts in node, with a small fake DOM: the pins inside the page (served with the
bridge) and comments.js in the bar. What crosses into the page is only ids, initials, colors,
anchors and flags; messages count only from the right origin and window."""

import json
import shutil
import subprocess
from importlib.resources import files

import pytest

from ontic_pages.shell import Assets

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(not NODE, reason="needs node")
STATIC = files("ontic_pages") / "static"
APEX = "https://pages.test"
CONTENT = "https://report.pages.test"
V1, V2 = "20261007T153000Z", "20261008T090000Z"

DOM = """
const vm = require("vm");
class El {
  constructor(tag) {
    this.tagName = tag.toUpperCase(); this.nodeType = 1; this.children = []; this.attrs = {};
    this.listeners = {}; this._text = ""; this.hidden = false; this.className = "";
    this.parentElement = null; this.isConnected = true; this.id = ""; this.value = "";
    this.rect = { left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0 };
    const style = { setProperty(k, v) { this[k] = v; } };
    this.style = style;
    const classes = new Set();
    this.classList = { add: (c) => classes.add(c), remove: (c) => classes.delete(c),
      contains: (c) => classes.has(c),
      toggle: (c, on) => (on === undefined ? !classes.has(c) : on)
        ? classes.add(c) : classes.delete(c) };
  }
  appendChild(c) { c.parentElement = this; this.children.push(c); return c; }
  remove() {
    const p = this.parentElement;
    if (p) p.children = p.children.filter((x) => x !== this);
  }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(""); }
  set textContent(v) { this._text = String(v); this.children = []; }
  get childNodes() { return this.children; }
  get previousElementSibling() {
    const s = this.parentElement ? this.parentElement.children : [];
    const i = s.indexOf(this);
    return i > 0 ? s[i - 1] : null;
  }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  hasAttribute(k) { return k in this.attrs; }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }
  fire(t, extra) {
    const ev = Object.assign({ preventDefault() {}, stopPropagation() {}, target: this },
                             extra || {});
    (this.listeners[t] || []).forEach((f) => f(ev));
  }
  getBoundingClientRect() { return this.rect; }
  attachShadow() { this.shadow = new El("shadow"); return this.shadow; }
  all() { return this.children.concat(...this.children.map((c) => c.all())); }
  querySelector(sel) {
    return this.all().filter((e) => e.tagName === sel.toUpperCase())[0] || null;
  }
  contains(x) { return x === this || this.all().indexOf(x) >= 0; }
  closest() { return null; }
  focus() {} select() {}
  get offsetWidth() { return 300; }
  get offsetHeight() { return 200; }
  get scrollHeight() { return 2000; }
  get scrollWidth() { return 1000; }
}
const docListeners = {}, winListeners = {};
const documentElement = new El("html");
const body = documentElement.appendChild(new El("body"));
"""

PINS = """
const posted = [];
const parent = { postMessage: (m, o) => posted.push([JSON.parse(JSON.stringify(m)), o]) };
const window = { parent, top: parent, scrollX: 0, scrollY: 100, innerHeight: 800,
  addEventListener: (t, f) => (winListeners[t] = winListeners[t] || []).push(f),
  requestAnimationFrame: (f) => f(), scrollTo() {} };
const main = body.appendChild(new El("div")); main.id = "main";
const p1 = main.appendChild(new El("p")); p1.textContent = "First";
const p2 = main.appendChild(new El("p")); p2.textContent = "  Depth   error table ";
p2.rect = { left: 100, top: 200, right: 300, bottom: 240, width: 200, height: 40 };
const byId = { "#main": [main] };
const selectors = { "#main > p:nth-of-type(2)": p2, "#main > p:nth-of-type(1)": p1 };
const document = { readyState: "complete", title: "t", documentElement, body,
  querySelector: (s) => s === "title" ? null : selectors[s] || null,
  querySelectorAll: (s) => byId[s] || [],
  createElement: (t) => new El(t), elementFromPoint: () => p2,
  addEventListener: (t, f) => (docListeners[t] = docListeners[t] || []).push(f) };
const location = new URL(CONTENT + "/_v/" + V1 + "/docs/?a=1");
vm.runInNewContext(SOURCE, { window, document, location, history: {}, URL, setTimeout });
function message(data, origin, source) {
  posted.length = 0;
  winListeners.message.forEach((f) => f({ data, origin: origin || APEX,
                                          source: source || parent }));
  return posted.slice();
}
const out = {};
out.foreign = [message({ ontic: "comment-mode", on: true }, "https://evil.test"),
               message({ ontic: "comment-mode", on: true }, APEX, {})];
out.untouched = documentElement.children.length;  // nothing drawn before the bar asks
message({ ontic: "comment-mode", on: true });
const host = documentElement.children[1];
const capture = host.shadow.children[0];
posted.length = 0;
capture.fire("click", { clientX: 150, clientY: 230 });
out.at = posted.slice();
out.pins = message({ ontic: "pins", seq: 7, pins: [
  { id: "a".repeat(16), initial: "O", color: "#2563eb", resolved: false, fallback: false,
    anchor: { selector: "#main > p:nth-of-type(2)", snippet: "Depth error table",
              fx: 0.5, fy: 0 } },
  { id: "b".repeat(16), initial: "O", color: "red", fallback: false,
    anchor: { selector: "#main > p:nth-of-type(1)", snippet: "changed since", x: 5, y: 5 } },
  { id: "c".repeat(16), initial: "O", fallback: true,
    anchor: { selector: "#gone", snippet: "", x: 40, y: 150 } },
]});
const layer = host.shadow.children[1];
out.placed = layer.children.map((n) => [n.style.display, n.style.left, n.style.top,
                                        n.style.background]);
out.focus = message({ ontic: "pin-focus", id: "a".repeat(16) });
posted.length = 0;
winListeners.keydown.forEach((f) => f({ key: "Escape" }));
out.escape = posted.slice();
console.log(JSON.stringify(out));
"""


def run(script: str, source: str, extra: dict | None = None):
    consts = {"APEX": APEX, "CONTENT": CONTENT, "V1": V1, "V2": V2, "SOURCE": source,
              **(extra or {})}  # fmt: skip
    head = "".join(f"const {k} = {json.dumps(v)};\n" for k, v in consts.items())
    out = subprocess.run([NODE, "-e", head + DOM + script], capture_output=True, text=True,
                         timeout=30)  # fmt: skip
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_pins_in_the_page():
    out = run(PINS, Assets(APEX).items["bridge.js"][0].decode())
    assert out["foreign"] == [[], []] and out["untouched"] == 1
    [[at, to]] = out["at"]
    assert to == APEX and at["ontic"] == "comment-at"
    assert at["point"] == {"x": 150, "y": 230}
    assert at["anchor"] == {
        "path": "/docs/?a=1",  # without /_v/<version>
        "selector": "#main > p:nth-of-type(2)",
        "fx": 0.25,
        "fy": 0.75,
        "snippet": "Depth error table",
        "x": 150,
        "y": 330,
    }
    # Placed by selector; the changed text with no fallback is an orphan; the fallback at x, y.
    assert out["pins"] == [[{"ontic": "orphans", "ids": ["b" * 16], "seq": 7}, APEX]]
    assert out["placed"] == [
        ["block", "200px", "176px", "#2563eb"],
        ["none", None, None, "#d97706"],  # an unsafe color is not used
        ["block", "40px", "26px", "#d97706"],
    ]
    assert out["focus"][-1][0]["ontic"] == "pin-open" and out["focus"][-1][0]["id"] == "a" * 16
    assert out["escape"] == [[{"ontic": "comment-escape"}, APEX]]


BAR = """
const sent = [], fetched = [];
const frameWindow = { postMessage: (m, o) => sent.push([JSON.parse(JSON.stringify(m)), o]) };
const els = {};
function make(id, tag) { const e = new El(tag || "div"); e.id = id; els[id] = e; return e; }
const frame = make("frame", "iframe"); frame.contentWindow = frameWindow;
frame.rect = { left: 0, top: 40, right: 1000, bottom: 800, width: 1000, height: 760 };
["cm", "cm-btn", "cm-count", "cm-more", "cm-menu", "cm-all", "cm-resolved"]
  .forEach((id) => make(id));
els["cm-menu"].hidden = true;
const facts = { page: { name: "report", content_origin: CONTENT, current: V2, viewer: VIEWER,
                        versions: [] },
                view: { path: "/", version: null } };
const document = {
  body, visibilityState: "visible", activeElement: null,
  getElementById: (id) => id === "ontic-facts" ? { textContent: JSON.stringify(facts) }
    : els[id] || null,
  createElement: (t) => new El(t), createElementNS: (ns, t) => new El(t),
  addEventListener: (t, f) => (docListeners[t] = docListeners[t] || []).push(f),
};
const window = { innerWidth: 1200, innerHeight: 900,
  addEventListener: (t, f) => (winListeners[t] = winListeners[t] || []).push(f),
  matchMedia: () => ({ matches: false }), confirm: () => true };
const location = { origin: APEX, href: APEX + "/report/", hash: HASH };
function fetch(url, init) {
  fetched.push([url, init.method, init.body || null]);
  return Promise.resolve({ ok: true, json: () => Promise.resolve(ANSWER) });
}
vm.runInNewContext(SOURCE, { window, document, location, fetch, setInterval() {},
  setTimeout: () => 0, Date, JSON, Promise, navigator: {} });
function message(data, origin, source) {
  sent.length = 0;
  (winListeners.message || []).forEach((f) => f({ data, origin: origin || CONTENT,
    source: source || frameWindow }));
  return sent.slice();
}
const out = {};
out.listens = !!winListeners.message;
(docListeners.DOMContentLoaded || []).forEach((f) => f());
setImmediate(() => setImmediate(() => {
  const pop = body.children.filter((c) => c.className === "cm-pop")[0];
  const side = body.children.filter((c) => c.className === "cm-side")[0];
  if (!pop) { console.log(JSON.stringify(out)); return; }
  out.fetched = fetched.slice();
  out.count = [els["cm-count"].textContent, els["cm-count"].hidden];
  out.pins = sent.filter((m) => m[0].ontic === "pins").map((m) => m[0]);
  // The bridge answers each pins message: which pins it could not place.
  const seq = out.pins[out.pins.length - 1].seq;
  out.stale = message({ ontic: "orphans", ids: [], seq: seq - 1 });
  out.focus = message({ ontic: "orphans", ids: ORPHANS, seq: seq })
    .filter((m) => m[0].ontic === "pin-focus").map((m) => m[0]);
  out.panel = side.hidden ? null : side.textContent;
  out.foreign = [message({ ontic: "pin-open", id: "a".repeat(16), point: { x: 1, y: 1 } },
                         "https://evil.test"),
                 message({ ontic: "pin-open", id: "a".repeat(16), point: { x: 1, y: 1 } },
                         CONTENT, {})];
  out.popHidden = pop.hidden;
  message({ ontic: "pin-open", id: "a".repeat(16), point: { x: 10, y: 10 } });
  out.popShown = !pop.hidden;
  out.popText = pop.textContent;
  out.active = sent.filter((m) => m[0].ontic === "pins").map((m) =>
    m[0].pins.filter((p) => p.active).map((p) => p.id))[0];
  // comment-at only in comment mode
  message({ ontic: "comment-at", anchor: { path: "/" }, point: { x: 1, y: 1 } });
  out.composeOff = pop.textContent.indexOf("New comment") >= 0;
  els["cm-btn"].fire("click");
  out.mode = sent.filter((m) => m[0].ontic === "comment-mode").map((m) => m[0].on);
  message({ ontic: "engaged" });
  message({ ontic: "comment-at", anchor: { path: "/" }, point: { x: 1, y: 1 } });
  out.composeOn = pop.textContent.indexOf("New comment") >= 0;
  console.log(JSON.stringify(out));
}));
"""

THREAD = {
    "id": "a" * 16,
    "version": V2,
    "anchor": {"path": "/", "selector": "p", "snippet": "Depth table", "fx": 0, "fy": 0},
    "created_by": "other@onticlabs.io",
    "created_by_name": "Other",
    "created_at": "2026-10-08T10:00:00+00:00",
    "resolved": False,
    "comments": [
        {
            "id": "b" * 16,
            "author": "other@onticlabs.io",
            "author_name": "Other",
            "body": "<b>secret</b> words",
            "created_at": "2026-10-08T10:00:00+00:00",
            "deleted": False,
            "mine": False,
        },  # fmt: skip
    ],
}


def bar(hash_: str = "", viewer: str = "me@onticlabs.io", orphans: list | None = None):
    answer = {"name": "report", "current": V2, "open": 1, "threads": [THREAD]}
    source = (STATIC / "comments.js").read_text()
    extra = {"ANSWER": answer, "HASH": hash_, "VIEWER": viewer, "ORPHANS": orphans or []}
    return run(BAR, source, extra)


def test_bar_comments():
    out = bar()
    assert out["listens"] and out["fetched"] == [["/_api/pages/report/comments", "GET", None]]
    assert out["count"] == ["1", False]
    # The page gets the pin: no text, no email.
    [pins] = out["pins"][-1:]
    text = json.dumps(pins)
    assert "secret" not in text and "@" not in text and "Other" not in text
    assert pins["pins"][0]["initial"] == "O" and pins["pins"][0]["fallback"] is True
    assert out["foreign"] == [[], []] and out["popHidden"] is True
    # A pin click opens the thread; its text is set as text, never parsed as HTML.
    assert out["popShown"] and "<b>secret</b> words" in out["popText"]
    assert "Depth table" in out["popText"] and out["active"] == ["a" * 16]
    assert out["composeOff"] is False and out["mode"] == [True] and out["composeOn"] is True
    assert out["focus"] == [] and out["panel"] is None


def test_bar_deep_link():
    # #comment=<id>: once loaded, the bridge is asked to place it, then to show it.
    out = bar(hash_="#comment=" + "a" * 16)
    assert out["stale"] == []  # an answer to an older pins message decides nothing
    assert out["focus"] == [{"ontic": "pin-focus", "id": "a" * 16}]
    # Its pin cannot be placed on this version: the thread opens in the side panel.
    out = bar(hash_="#comment=" + "a" * 16, orphans=["a" * 16])
    assert out["focus"] == [] and "<b>secret</b> words" in out["panel"]


def test_bar_comments_need_a_viewer():
    assert bar(viewer="")["listens"] is False


def test_no_html_from_strings():
    for fname in ("comments.js", "pins.js"):
        source = (STATIC / fname).read_text()
        assert "innerHTML" not in source and "insertAdjacentHTML" not in source, fname
