"""Edit text in place, in node: the page's side (edit-bridge.js, in the served bridge) and the
bar's side (edit.js, in the served bar.js), each with a small fake DOM around it."""

import json
import shutil
import subprocess

import pytest

from ontic_pages.shell import Assets

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(not NODE, reason="needs node")
APEX = "https://pages.test"
CONTENT = "https://report.pages.test"

DOM = r"""
const vm = require("vm");
class Text {
  constructor(data) { this.nodeType = 3; this.data = data; this.parentNode = null; }
  get textContent() { return this.data; }
}
class Classes {
  constructor() { this.set = new Set(); }
  add(...c) { c.forEach((x) => this.set.add(x)); }
  remove(...c) { c.forEach((x) => this.set.delete(x)); }
  toggle(c, on) {
    if (on === undefined) on = !this.set.has(c);
    if (on) this.set.add(c); else this.set.delete(c);
    return on;
  }
  contains(c) { return this.set.has(c); }
}
function target(extra) {
  return Object.assign({ listeners: [], addEventListener(type, f, opts) {
    this.listeners.push({ type, f, capture: opts === true || !!(opts && opts.capture) });
  } }, extra || {});
}
// Capture listeners first, then the others; stopPropagation ends it.
function fire(on, type, props) {
  const event = Object.assign({ type, defaultPrevented: false, stopped: false,
    preventDefault() { this.defaultPrevented = true; },
    stopPropagation() { this.stopped = true; } }, props || {});
  for (const phase of [true, false]) {
    for (const x of on.listeners.slice()) {
      if (x.type === type && x.capture === phase && !event.stopped) x.f(event);
    }
  }
  return event;
}
class El {
  constructor(tag, attrs, kids) {
    Object.assign(this, target());
    this.nodeType = 1; this.tagName = tag.toUpperCase(); this.attrs = {}; this.childNodes = [];
    this.parentNode = null;
    this.style = { outline: "", outlineOffset: "", setProperty(k, v) { this[k] = v; } };
    this.classList = new Classes(); this.hidden = false; this.disabled = false;
    Object.entries(attrs || {}).forEach(([k, v]) => this.setAttribute(k, v));
    (kids || []).forEach((k) => this.appendChild(typeof k === "string" ? new Text(k) : k));
  }
  set className(v) {
    this.classList = new Classes();
    v.split(/\s+/).filter(Boolean).forEach((c) => this.classList.add(c));
  }
  get className() { return [...this.classList.set].join(" "); }
  get id() { return this.attrs.id || ""; }
  set id(v) { this.attrs.id = v; }
  appendChild(k) {
    if (k.parentNode) k.parentNode.removeChild(k);
    k.parentNode = this; this.childNodes.push(k); return k;
  }
  removeChild(k) { this.childNodes = this.childNodes.filter((c) => c !== k); k.parentNode = null; }
  insertBefore(k, ref) {
    if (!ref) return this.appendChild(k);
    if (k.parentNode) k.parentNode.removeChild(k);
    k.parentNode = this; this.childNodes.splice(this.childNodes.indexOf(ref), 0, k); return k;
  }
  get nextSibling() { const s = this.parentNode.childNodes; return s[s.indexOf(this) + 1] || null; }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }
  cloneNode() { return new El(this.tagName.toLowerCase(), this.attrs); }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(""); }
  set textContent(v) {
    this.childNodes = [];
    if (v !== "" && v != null) this.appendChild(new Text(String(v)));
  }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  setAttribute(k, v) { this.attrs[k] = String(v); if (k === "class") this.className = String(v); }
  removeAttribute(k) { delete this.attrs[k]; }
  hasAttribute(k) { return k in this.attrs; }
  matches(sel) {
    return sel.split(",").some((part) => {
      if (part.trim() === "*") return true;
      const m = part.trim().match(/^([a-z0-9]*)((?:\.[a-z-]+)*)(?:\[([a-z-]+)\])?$/i);
      if (!m) throw new Error("selector " + part);
      if (m[1] && m[1].toUpperCase() !== this.tagName) return false;
      const classes = m[2].split(".").filter(Boolean);
      if (!classes.every((c) => this.classList.contains(c))) return false;
      return !m[3] || this.hasAttribute(m[3]);
    });
  }
  closest(sel) {
    for (let n = this; n && n.nodeType === 1; n = n.parentNode) if (n.matches(sel)) return n;
    return null;
  }
  querySelectorAll(sel) {
    const out = [];
    const walk = (e) => e.childNodes.forEach((c) => {
      if (c.nodeType === 1) { if (c.matches(sel)) out.push(c); walk(c); }
    });
    walk(this);
    return out;
  }
  querySelector(sel) { // ".bar .grow": the last part is enough here
    const parts = sel.trim().split(/\s+/);
    return this.querySelectorAll(parts[parts.length - 1])[0] || null;
  }
  click() { fire(this, "click", { target: this }); }
}
const E = (t, a, k) => new El(t, a, k);
const tick = () => new Promise((resolve) => setImmediate(resolve));
"""


BRIDGE = r"""
const posted = [];
const parent = { postMessage: (m, o) => posted.push([JSON.parse(JSON.stringify(m)), o]) };
const window = target({ parent, top: parent, scrollY: 0,
  getComputedStyle: (e) => ({ cursor: e.cursor || "auto" }) });
const h1 = E("h1", {}, ["Title & more"]);
const bold = E("b", {}, ["bold"]);
const mixed = E("p", {}, ["Hello ", bold, " tail"]);
const plain = E("p", {}, ["Plain para"]);
const clock = E("span", {}, ["10:00"]);
const link = E("a", { href: APEX + "/other/" }, ["A link"]);
link.href = APEX + "/other/";
const inLink = E("span", {}, ["inside a link"]);
const inButton = E("span", {}, ["Run"]);
const roleButton = E("div", { role: "button" }, ["Fake button"]);
const inRoleLink = E("span", {}, ["Fake link"]);
const clicky = E("div", { onclick: "go()" }, ["Clicky"]);
const tabby = E("span", { tabindex: "0" }, ["Tabby"]);
const inMain = E("p", {}, ["In main"]);  // main has tabindex=-1 (a skip link's target)
const summary = E("summary", {}, ["More"]);
const inSummary = E("span", {}, ["More text"]);
const label = E("label", {}, ["Name"]);
const card = E("div", {}, ["Card title"]);
card.cursor = "pointer";  // the page made it clickable
const own = E("div", { contenteditable: "true" }, ["their own editor"]);
const inOwn = E("p", {}, ["in their editor"]);
const pre = E("pre", {}, ["code\nblock"]);
const inSvg = E("span", {}, ["in svg"]);
const empty = E("p"), blank = E("li", {}, ["   "]), script = E("script", {}, ["var x"]);
const body = E("body", {}, [h1, mixed, plain, clock, link, E("a", {}, [inLink]),
  E("button", {}, ["Go"]), E("button", {}, [inButton]), roleButton,
  E("div", { role: "link" }, [inRoleLink]), clicky, tabby,
  E("main", { tabindex: "-1" }, [inMain]),
  E("details", {}, [summary, E("summary", {}, [inSummary])]),
  label, card, own, E("div", { contenteditable: "true" }, [inOwn]), pre,
  E("svg", {}, [inSvg]), empty, blank, script]);
let blurred = 0;
h1.blur = () => { blurred += 1; document.activeElement = body; };
const document = target({ readyState: "complete", title: "t", body, querySelector: () => null,
  createElement: (t) => new El(t), activeElement: body, documentElement: E("html") });
const location = new URL(CONTENT + "/a/b.html");
vm.runInNewContext(SOURCE, { window, document, location, history: {}, URL, setTimeout,
  TextEncoder });
function msg(data, origin, source) {
  posted.length = 0;
  fire(window, "message", { data, origin: origin || APEX, source: source || parent });
  return posted.slice();
}
function hoverAll() {
  body.querySelectorAll("*").forEach((e) => fire(window, "pointerover", { target: e }));
}
function editable() {
  return body.querySelectorAll("*")
    .filter((e) => e.getAttribute("contenteditable") === "plaintext-only")
    .map((e) => e.tagName.toLowerCase() + ":" + e.textContent);
}
function type(el, text) {
  posted.length = 0;
  fire(window, "beforeinput", { target: el });
  el.textContent = text;
  fire(window, "input", { target: el });
  return posted.slice();
}
const out = {};
// Not the owner's page, or not yet told: nothing is editable.
hoverAll();
out.notYet = editable();
out.ignored = [msg({ ontic: "edit-mode", on: true }, "https://evil.test"),
  msg({ ontic: "edit-mode", on: true }, APEX, {})];
hoverAll();
out.stillNot = editable();
out.start = msg({ ontic: "edit-mode", on: true });
out.lazy = editable();  // nothing changes in the page until the pointer comes
fire(window, "pointerover", { target: h1 });
out.hovered = [editable(), h1.style.outline, h1.style.outlineOffset];
fire(window, "pointerout", { target: h1 });
out.unhovered = [h1.style.outline, editable()];
hoverAll();
out.editable = editable();
document.activeElement = h1;
fire(window, "focusin", { target: h1 });
out.focused = h1.style.outline;
fire(window, "focusout", { target: h1 });
document.activeElement = body;
out.blurredOutline = h1.style.outline;
// The page's own outline stays while hovered, and comes back after the focus.
plain.style.outline = "3px solid green";
fire(window, "pointerover", { target: plain });
const own1 = plain.style.outline;
fire(window, "focusin", { target: plain });
const own2 = plain.style.outline;
fire(window, "focusout", { target: plain });
out.ownOutline = [own1, own2, plain.style.outline];
// A script changes a text: not a change. Typing is.
posted.length = 0;
clock.textContent = "10:01";
out.script = posted.slice();
out.typed = type(h1, "Title & more!");  // a browser types a no-break space
out.again = type(h1, "Title & more!");  // the same count is not sent twice
out.clockAfter = msg({ ontic: "edit-mode", on: true });
// Links still work: the bridge hands an apex link to the bar as always.
posted.length = 0;
let e = fire(window, "click", { target: link, button: 0 });
out.click = [e.defaultPrevented, posted.slice()];
out.keys = [fire(window, "keydown", { key: "Enter", target: h1 }).defaultPrevented,
  fire(window, "keydown", { key: "Enter", target: pre }).defaultPrevented,
  fire(window, "keydown", { key: "j", target: h1 }).stopped,
  fire(window, "keydown", { key: "j", target: body }).stopped];
posted.length = 0;
e = fire(window, "keydown", { key: "Escape", target: h1 });
out.escape = [e.defaultPrevented, blurred, posted.slice()];
// Cmd/Ctrl+S anywhere in the page asks the bar to save.
posted.length = 0;
out.saveKeys = [fire(window, "keydown", { key: "s", metaKey: true, target: body }).defaultPrevented,
  fire(window, "keydown", { key: "S", ctrlKey: true, target: plain }).defaultPrevented,
  posted.slice()];
// Comment mode suspends editing; leaving it resumes.
msg({ ontic: "comment-mode", on: true });
fire(window, "pointerover", { target: inMain });
out.commenting = [editable(), type(h1, "Title & more!?"), h1.textContent];
h1.textContent = "Title & more!";
msg({ ontic: "comment-mode", on: false });
out.resumedComment = editable();
// Save: the changes go to the bar; the new text stays, nothing is editable.
out.save = msg({ ontic: "edit-mode", on: false, save: true });
out.saved = [h1.textContent, editable(), h1.style.outline];
// A refused save: editing resumes with the changes.
out.resume = msg({ ontic: "edit-mode", on: true });
out.resumed = editable();
// A save that went through: what is on screen is the original now (a typed no-break space is
// the plain one saved), nothing reloads, and editing goes on against the saved text.
type(h1, "Title & more!");
out.save2 = msg({ ontic: "edit-mode", on: false, save: true });
out.rebased = msg({ ontic: "edit-mode", on: true, saved: true });
out.afterSave = [h1.textContent, editable()];
out.typedAgain = type(h1, "Title & more!!");
out.save3 = msg({ ontic: "edit-mode", on: false, save: true });
out.resume3 = msg({ ontic: "edit-mode", on: true });  // refused: the change is still there
// Saved, said to a page that has not sent its edits (another page sent them): nothing changes.
out.notMine = [msg({ ontic: "edit-mode", on: true, saved: true }), h1.textContent];
// Discard: every original text comes back; the page's own editor is left alone.
out.discard = msg({ ontic: "edit-mode", on: true, discard: true });
out.restored = [h1.textContent, editable(), own.getAttribute("contenteditable"),
  fire(window, "keydown", { key: "s", metaKey: true, target: body }).defaultPrevented];
fire(window, "pointerover", { target: plain });
type(plain, "x".repeat(20001));
out.tooLong = msg({ ontic: "edit-mode", on: false, save: true });
console.log(JSON.stringify(out));
"""

BAR = r"""
const PAGE = { name: "report", content_origin: CONTENT, current: "v1", role: ROLE,
  visibility: "ontic", published_by: "owner@onticlabs.io", email_domain: "onticlabs.io",
  versions: [{ version: "v1", published_at: "", description: "" }] };
const facts = { page: PAGE, view: { path: "/", version: VIEWING } };
const framePosts = [];
const frame = E("iframe", { id: "frame" });
frame.contentWindow = {
  postMessage: (m, o) => framePosts.push([JSON.parse(JSON.stringify(m)), o]) };
const access = E("select", { id: "s-access" });
access.options = [];
access.selectedIndex = 0;
const ids = ["m-by", "m-owner", "m-time", "m-desc", "m-versions", "old", "s-note", "s-explain",
  "s-owner", "title-btn", "title-menu", "info-btn", "info-panel", "share-btn", "share-panel",
  "m-raw", "slow", "retry"];
const stage = E("main", { id: "stage" }, [frame,
  E("div", { id: "status" }, [E("div", { class: "spinner" })])]);
const bar = E("header", { class: "bar" }, [E("span", { class: "grow" }), access,
  ...ids.map((id) => E("div", { id }))]);
const body = E("body", {}, [bar, stage]);
let swaps = 0; // a new version's frame added to the stage
const append = stage.appendChild.bind(stage);
stage.appendChild = (k) => { swaps += 1; return append(k); };
const byId = (id) => (id === "ontic-facts" ? { textContent: JSON.stringify(facts) }
  : body.querySelectorAll("*").find((n) => n.id === id) || null);
const document = target({ body, getElementById: byId, visibilityState: "visible",
  createElement: (t) => new El(t), querySelector: (s) => body.querySelector(s),
  querySelectorAll: (s) => body.querySelectorAll(s) });
const window = target({});
const fetches = [], answers = [];
function fetch(url, options) {
  fetches.push([url, options && options.method || "GET",
    options && options.body ? JSON.parse(options.body) : null]);
  const a = answers.shift();
  const response = { ok: a.ok, status: a.status, json: () => Promise.resolve(a.body) };
  return a.gate ? a.gate.then(() => response) : Promise.resolve(response);
}
const clock = { now: 1e12 };  // Date.now, moved on by hand (polls are 2 s apart at least)
class FakeDate extends Date {}
FakeDate.now = () => clock.now;
const location = { origin: APEX, href: APEX + "/report/", hash: "", assign() {} };
vm.runInNewContext(SOURCE, { window, document, location, history: { replaceState() {} }, URL,
  fetch, JSON, Date: FakeDate, setTimeout: () => 0, clearTimeout() {}, setInterval: () => 0 });
fire(document, "DOMContentLoaded");
const q = (cls) => body.querySelector("." + cls);
function message(data, origin) {
  framePosts.length = 0;
  fire(window, "message", { data, origin: origin || CONTENT, source: frame.contentWindow });
  return framePosts.slice();
}
const shown = () => !q("edit-pop").hidden && !q("edit-tools").hidden;
const unload = () => fire(window, "beforeunload", {}).defaultPrevented;
(async () => {
  const out = { button: !!q("edit-btn"), ready: message({ ontic: "ready" }) };
  out.zero = [message({ ontic: "edit-state", changes: 0 }), shown(), unload()];
  message({ ontic: "edit-state", changes: 3 });
  out.notMine = shown();
  if (ROLE !== "owner" || VIEWING) return console.log(JSON.stringify(out));
  message({ ontic: "edit-state", changes: 2 });
  message({ ontic: "edit-state", changes: 9 }, "https://other.pages.test");
  out.counter = [shown(), q("edit-count").textContent, q("edit-tools").title,
    body.classList.contains("editing"), unload()];

  // Save while a poll is on its way (answered after the save, with the facts before it).
  let release;
  answers.push({ ok: true, status: 200, body: PAGE, gate: new Promise((r) => { release = r; }) });
  fire(window, "focus");
  framePosts.length = 0;
  q("edit-save").click();
  out.saving = [framePosts.slice(), q("edit-count").textContent, q("edit-save").disabled];
  const next = Object.assign({}, PAGE,
    { current: "v2", versions: [{ version: "v2" }, { version: "v1" }] });
  answers.push({ ok: true, status: 200, body: { version: "v2", page: next } });
  message({ ontic: "edits", path: "/", changes: [{ before: "a", after: "b" }] });
  out.twice = message({ ontic: "edits", path: "/", changes: [] }); // ignored while sending
  await tick(); await tick(); await tick();
  out.fetch = fetches.filter((f) => f[1] === "POST");
  // Saved: the frame keeps the text it shows (no new frame); the bar takes v2 as current.
  out.saved = [shown(), q("edit-done").hidden, swaps, window.onticBar.page().current,
    framePosts.slice()];
  release();
  await tick(); await tick(); await tick();
  out.stalePoll = [swaps, window.onticBar.page().current];  // the older facts are dropped
  clock.now += 5000;
  answers.push({ ok: true, status: 200, body: next });
  fire(window, "focus");
  await tick(); await tick();
  out.samePoll = swaps;  // the poll brings v2: it is not loaded again

  // Cmd/Ctrl+S in the page: a refused save shows its error, and the page edits on.
  fetches.length = 0;
  message({ ontic: "edit-state", changes: 1 });
  out.frameKey = message({ ontic: "edit-state", changes: 1, save: true });
  answers.push({ ok: false, status: 409, body: { error: "a newer version was published" } });
  framePosts.length = 0;
  fire(window, "message", { origin: CONTENT, source: frame.contentWindow,
    data: { ontic: "edits", path: "/", changes: [{ before: "c", after: "d" }] } });
  await tick(); await tick(); await tick();
  out.refused = [fetches[0][2].version, q("error").textContent, q("edit-panel").hidden,
    framePosts.slice(), q("edit-count").textContent];
  message({ ontic: "edit-state", changes: 1 });  // the page's answer keeps the error up
  out.errorStays = q("edit-panel").hidden;

  // Ctrl+S in the bar saves too.
  framePosts.length = 0;
  out.barKey = [fire(document, "keydown", { key: "s", ctrlKey: true }).defaultPrevented,
    framePosts.slice()];
  message({ ontic: "edits", path: "/", changes: [], error: "too long" });
  await tick();

  // A version published meanwhile does not replace the page with changes.
  const before = swaps;
  answers.push({ ok: true, status: 200, body: Object.assign({}, next, { current: "v3" }) });
  clock.now += 5000;
  fire(window, "focus");
  await tick(); await tick();
  out.held = swaps - before;

  // Discard asks first, in the bar; Keep editing and Escape go back.
  q("edit-discard").click();
  out.confirm = [q("edit-confirm").hidden, q("edit-panel").hidden, q("edit-confirm").textContent];
  q("edit-keep").click();
  out.kept = [q("edit-panel").hidden, shown()];
  q("edit-discard").click();
  fire(document, "keydown", { key: "Escape" });
  out.escape = q("edit-panel").hidden;
  q("edit-discard").click();
  framePosts.length = 0;
  q("edit-really").click();
  out.discarded = [framePosts.slice(), shown(), swaps - before, unload()];
  message({ ontic: "edit-state", changes: 0 });  // the page's answer starts no second swap
  out.discarded.push(swaps - before);

  // The page loaded again with changes in it: they are gone, and the bar says so.
  message({ ontic: "edit-state", changes: 2 });
  out.reload = [message({ ontic: "ready" }), shown(), q("error").textContent];

  // A save answered with another version current (a publish raced it): that one fades in.
  message({ ontic: "edit-state", changes: 1 });
  q("edit-save").click();
  const swapsBefore = swaps;
  answers.push({ ok: true, status: 200,
    body: { version: "v4", page: Object.assign({}, next, { current: "v5" }) } });
  framePosts.length = 0;
  fire(window, "message", { origin: CONTENT, source: frame.contentWindow,
    data: { ontic: "edits", path: "/", changes: [{ before: "e", after: "f" }] } });
  await tick(); await tick(); await tick();
  out.raced = [swaps - swapsBefore, framePosts.slice(), window.onticBar.page().current,
    q("edit-done").hidden];

  // Another document loads in the frame while a save is on its way (a reload): its answer
  // leaves that document's edits alone and only brings the saved version into the facts.
  message({ ontic: "ready" });
  message({ ontic: "edit-state", changes: 1 });
  q("edit-save").click();
  let release2;
  answers.push({ ok: true, status: 200, gate: new Promise((r) => { release2 = r; }),
    body: { version: "v6", page: Object.assign({}, next, { current: "v6" }) } });
  message({ ontic: "edits", path: "/", changes: [{ before: "g", after: "h" }] });
  message({ ontic: "ready" });
  message({ ontic: "edit-state", changes: 2 });  // typed in the new document
  const swaps2 = swaps;
  framePosts.length = 0;
  release2();
  await tick(); await tick(); await tick();
  out.otherDoc = [framePosts.slice(), q("edit-count").textContent, shown(),
    window.onticBar.page().current, swaps - swaps2];
  q("edit-discard").click();
  q("edit-really").click();
  out.otherDoc.push(swaps - swaps2);  // nothing unsaved now: the saved version fades in
  console.log(JSON.stringify(out));
})();
"""


def run(script: str, source: str, **values):
    head = f"const APEX = {json.dumps(APEX)}, CONTENT = {json.dumps(CONTENT)};\n"
    head += f"const SOURCE = {json.dumps(source)};\n"
    head += "".join(f"const {k} = {json.dumps(v)};\n" for k, v in values.items())
    out = subprocess.run(
        [NODE, "-e", head + DOM + script], capture_output=True, text=True, timeout=30
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def served(fname: str) -> str:
    return Assets(APEX).items[fname][0].decode()


def state(changes: int, **extra) -> list:
    return [{"ontic": "edit-state", "changes": changes, **extra}, APEX]


def test_bridge_editable_set():
    out = run(BRIDGE, served("bridge.js"))
    assert out["notYet"] == out["stillNot"] == []  # only once the bar says so (the owner)
    assert out["ignored"] == [[], []]  # other origins and windows are ignored
    assert out["start"] == [state(0)]
    assert out["lazy"] == []
    # No highlight: hovering makes it editable and changes nothing else.
    assert out["hovered"] == [["h1:Title & more"], "", ""]
    assert out["unhovered"] == ["", ["h1:Title & more"]]
    # Text-only elements; never links, buttons, labels, summaries, roles, onclick, a tabindex,
    # a pointer cursor, the page's own editors, svg or empty ones, nor anything inside those.
    assert out["editable"] == [
        "h1:Title & more", "b:bold", "p:Plain para", "span:10:00", "p:In main", "pre:code\nblock"
    ]  # fmt: skip
    # The browser's focus ring is off while focused; the page's own outline comes back.
    assert out["focused"] == "none" and out["blurredOutline"] == ""
    assert out["ownOutline"] == ["3px solid green", "none", "3px solid green"]


def test_bridge_counts_only_typed_changes():
    out = run(BRIDGE, served("bridge.js"))
    assert out["script"] == []  # a script changed a text: not a change
    assert out["typed"] == [state(1)] and out["again"] == []
    assert out["clockAfter"] == [state(1)]
    assert out["click"] == [True, [[{"ontic": "open", "url": f"{APEX}/other/"}, APEX]]]
    assert out["keys"] == [True, False, True, False]  # Enter only in pre; typing stays here
    assert out["escape"] == [True, 1, []]  # Escape leaves the text, nothing else
    assert out["saveKeys"] == [True, True, [state(1, save=True), state(1, save=True)]]


def test_bridge_comment_mode_save_and_discard():
    out = run(BRIDGE, served("bridge.js"))
    editable, typed, text = out["commenting"]
    assert editable == [] and typed == [] and text == "Title & more!?"  # not counted
    assert "h1:Title & more!" in out["resumedComment"]
    assert out["save"] == [[{
        "ontic": "edits", "path": "/a/b.html",
        "changes": [{"before": "Title & more", "after": "Title & more!"}],
    }, APEX]]  # fmt: skip
    assert out["saved"] == ["Title & more!", [], ""]  # the new text stays on screen
    assert out["resume"] == [state(1)] and out["resumed"] == ["h1:Title & more!"]
    edits = lambda before, after: [[{  # noqa: E731
        "ontic": "edits", "path": "/a/b.html", "changes": [{"before": before, "after": after}],
    }, APEX]]  # fmt: skip
    # Saved: the counter goes to 0 without a reload, and the next change diffs against it.
    assert out["save2"] == edits("Title & more", "Title & more!")
    assert out["rebased"] == [state(0)]
    assert out["afterSave"] == ["Title & more!", ["h1:Title & more!"]]
    assert out["typedAgain"] == [state(1)]
    assert out["save3"] == edits("Title & more!", "Title & more!!")
    assert out["resume3"] == [state(1)]
    assert out["notMine"] == [[state(1)], "Title & more!!"]  # still one change, unsaved
    assert out["discard"] == [state(0)]
    # Discard puts back the text as last saved.
    assert out["restored"] == ["Title & more!", [], "true", False]
    (message, origin), *_ = out["tooLong"]
    assert message["changes"] == [] and "too long" in message["error"]


NOTE = "Text only. Saved as a new version; older versions stay in the title menu."


def test_bar_edit_flow():
    out = run(BAR, served("bar.js"), ROLE="owner", VIEWING=None)
    assert out["button"] is False  # no Edit button: editing is always on
    assert out["ready"] == [[{"ontic": "edit-mode", "on": True}, CONTENT]]
    assert out["zero"] == [[], False, False]  # nothing shows without a change
    assert out["notMine"] is True
    assert out["counter"] == [True, "2 changes", NOTE, True, True]
    assert out["saving"] == [
        [[{"ontic": "edit-mode", "on": False, "save": True}, CONTENT]], "Saving…", True
    ]  # fmt: skip
    assert out["fetch"] == [[
        "/_api/pages/report/edits", "POST",
        {"version": "v1", "path": "/", "changes": [{"before": "a", "after": "b"}]},
    ]]  # fmt: skip
    assert out["twice"] == []
    # Saved, and no frame is loaded: the page's text becomes the original, editing goes on.
    saved_post = [[{"ontic": "edit-mode", "on": True, "saved": True}, CONTENT]]
    assert out["saved"] == [False, False, 0, "v2", saved_post]
    assert out["stalePoll"] == [0, "v2"]  # facts asked before the save are dropped
    assert out["samePoll"] == 0  # the saved version is never loaded again
    assert out["frameKey"] == [[{"ontic": "edit-mode", "on": False, "save": True}, CONTENT]]
    version, error, panel_hidden, posts, count = out["refused"]
    assert version == "v2" and error == "a newer version was published" and not panel_hidden
    assert posts == [[{"ontic": "edit-mode", "on": True}, CONTENT]]  # back to editing
    assert count == "1 change" and out["errorStays"] is False
    assert out["barKey"] == [True, [[{"ontic": "edit-mode", "on": False, "save": True}, CONTENT]]]
    assert out["held"] == 0
    assert out["confirm"] == [False, False, "Discard 1 change?Keep editingDiscard"]
    assert out["kept"] == [True, True] and out["escape"] is True
    posts, still_shown, new_frames, warns, after_answer = out["discarded"]
    assert posts == [[{"ontic": "edit-mode", "on": True, "discard": True}, CONTENT]]
    assert (still_shown, warns) == (False, False)
    assert new_frames == after_answer == 1  # the version published meanwhile fades in now
    posts, still_shown, error = out["reload"]
    assert posts == [[{"ontic": "edit-mode", "on": True}, CONTENT]] and still_shown is False
    assert error == "The page reloaded; unsaved changes are gone."
    # A publish made another version current during the save: that one fades in.
    assert out["raced"] == [1, [], "v5", False]
    # A save answered after the frame loaded another document: no saved:true to it, its own
    # changes stay unsaved, the new version is current in the bar and waits for them.
    assert out["otherDoc"] == [[], "2 changes", True, "v6", 0, 1]


@pytest.mark.parametrize("role, viewing", [("viewer", None), ("owner", "v0")])
def test_bar_edit_only_for_the_owner_on_the_current_version(role, viewing):
    out = run(BAR, served("bar.js"), ROLE=role, VIEWING=viewing)
    assert out == {"button": False, "ready": [], "zero": [[], False, False], "notMine": False}
