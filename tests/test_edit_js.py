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
    this.parentNode = null; this.style = { outline: "", outlineOffset: "" };
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
const window = target({ parent, top: parent, scrollY: 0 });
const h1 = E("h1", {}, ["Title & more"]);
const mixed = E("p", {}, ["Hello ", E("b", {}, ["bold"]), " tail"]);
const plain = E("p", {}, ["Plain para"]);
const link = E("a", { href: APEX + "/other/" }, ["A link"]);
link.href = APEX + "/other/";
const own = E("div", { contenteditable: "true" }, ["their own editor"]);
const pre = E("pre", {}, ["code\nblock"]);
const body = E("body", {}, [h1, mixed, plain, link, E("svg", {}, [E("span", {}, ["in svg"])]),
  E("p"), E("li", {}, ["   "]), own, pre, E("script", {}, ["var x"])]);
const document = target({ readyState: "complete", title: "t", body, querySelector: () => null,
  createElement: (t) => new El(t) });
const location = new URL(CONTENT + "/a/b.html");
vm.runInNewContext(SOURCE, { window, document, location, history: {}, URL, setTimeout,
  TextEncoder });
function msg(data, origin, source) {
  posted.length = 0;
  fire(window, "message", { data, origin: origin || APEX, source: source || parent });
  return posted.slice();
}
function editable() {
  return body.querySelectorAll("*")
    .filter((e) => e.getAttribute("contenteditable") === "plaintext-only")
    .map((e) => e.tagName.toLowerCase() + ":" + e.textContent);
}
const out = {};
out.ignored = [msg({ ontic: "edit-mode", on: true }, "https://evil.test"),
  msg({ ontic: "edit-mode", on: true }, APEX, {}), editable()];
out.start = msg({ ontic: "edit-mode", on: true });
out.editable = editable();
out.outlined = [h1.style.outline, h1.style.outlineOffset, mixed.style.outline,
  own.getAttribute("contenteditable")];
plain.textContent = "Plain paragraph";
posted.length = 0;
fire(window, "input", { target: plain });
out.input = posted.slice();
posted.length = 0;
let e = fire(window, "click", { target: link, button: 0 });
out.click = [e.defaultPrevented, e.stopped, posted.length];
out.clickElsewhere = fire(window, "click", { target: mixed, button: 0 }).defaultPrevented;
posted.length = 0;
e = fire(window, "keydown", { key: "Escape", target: h1 });
out.escape = [e.defaultPrevented, posted.slice()];
out.keys = [fire(window, "keydown", { key: "Enter", target: h1 }).defaultPrevented,
  fire(window, "keydown", { key: "Enter", target: pre }).defaultPrevented,
  fire(window, "keydown", { key: "j", target: h1 }).stopped,
  fire(window, "keydown", { key: "j", target: body }).stopped];
h1.textContent = "Title & more!";  // a browser types a no-break space
out.save = msg({ ontic: "edit-mode", on: false, save: true });
out.saved = [h1.textContent, h1.getAttribute("contenteditable"), h1.style.outline];
out.heldClick = fire(window, "click", { target: link, button: 0 }).defaultPrevented;
out.resume = msg({ ontic: "edit-mode", on: true });
out.resumed = editable().length;
out.cancel = msg({ ontic: "edit-mode", on: false });
out.restored = [h1.textContent, plain.textContent, editable().length,
  own.getAttribute("contenteditable"), h1.style.outline];
posted.length = 0;
e = fire(window, "click", { target: link, button: 0 });
out.clickAfter = [e.defaultPrevented, posted.slice()];
msg({ ontic: "edit-mode", on: true });
plain.textContent = "x".repeat(20001);
out.tooLong = msg({ ontic: "edit-mode", on: false, save: true });
msg({ ontic: "edit-mode", on: false });
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
  "s-owner", "title-btn", "title-menu", "share-btn", "share-panel", "m-raw", "slow", "retry"];
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
  return Promise.resolve({ ok: a.ok, status: a.status, json: () => Promise.resolve(a.body) });
}
const location = { origin: APEX, href: APEX + "/report/", hash: "", assign() {} };
vm.runInNewContext(SOURCE, { window, document, location, history: { replaceState() {} }, URL,
  fetch, JSON, Date, setTimeout: () => 0, clearTimeout() {}, setInterval: () => 0 });
fire(document, "DOMContentLoaded");
const q = (cls) => body.querySelector("." + cls);
function message(data, origin) {
  framePosts.length = 0;
  fire(window, "message", { data, origin: origin || CONTENT, source: frame.contentWindow });
  return framePosts.slice();
}
function frames() { return swaps; }
(async () => {
  const out = { canEdit: !q("edit-btn").hidden, tools: q("edit-tools").hidden };
  if (ROLE !== "owner" || VIEWING) return console.log(JSON.stringify(out));
  q("edit-btn").click();
  out.start = framePosts.slice();
  out.editing = [q("edit-btn").hidden, q("edit-tools").hidden, body.classList.contains("editing"),
    q("edit-note").textContent];
  message({ ontic: "edit-state", changes: 2, editable: 5 });
  message({ ontic: "edit-state", changes: 9 }, "https://other.pages.test");
  out.count = q("edit-count").textContent;

  // Save: the page's changes go to the gateway, the new version fades in.
  framePosts.length = 0;
  q("edit-save").click();
  out.saving = [framePosts.slice(), q("edit-count").textContent, q("edit-save").disabled];
  const next = Object.assign({}, PAGE,
    { current: "v2", versions: [{ version: "v2" }, { version: "v1" }] });
  answers.push({ ok: true, status: 200, body: { version: "v2", page: next } });
  message({ ontic: "edits", path: "/", changes: [{ before: "a", after: "b" }] });
  await tick(); await tick(); await tick();
  out.fetch = fetches.slice();
  out.saved = [q("edit-tools").hidden, q("edit-btn").hidden, q("edit-done").hidden, frames()];

  // A refused save: the error shows, and the page goes back to editing.
  fetches.length = 0;
  q("edit-btn").click();
  message({ ontic: "edit-state", changes: 1, editable: 5 });
  q("edit-save").click();
  answers.push({ ok: false, status: 409, body: { error: "a newer version was published" } });
  framePosts.length = 0;
  fire(window, "message", { origin: CONTENT, source: frame.contentWindow,
    data: { ontic: "edits", path: "/", changes: [{ before: "c", after: "d" }] } });
  await tick(); await tick(); await tick();
  out.refused = [fetches[0][2].version, q("error").textContent, q("edit-panel").hidden,
    framePosts.slice(), q("edit-count").textContent];

  // A version published meanwhile does not replace the page being edited.
  const before = frames();
  answers.push({ ok: true, status: 200, body: Object.assign({}, next, { current: "v3" }) });
  fire(window, "focus");
  await tick(); await tick();
  out.held = frames() - before;

  // Cancel with changes asks first; Escape in the page does too.
  q("edit-cancel").click();
  out.confirm = [q("edit-confirm").hidden, q("edit-panel").hidden, q("edit-confirm").textContent];
  q("edit-keep").click();
  out.kept = [q("edit-panel").hidden, q("edit-tools").hidden];
  message({ ontic: "edit-state", changes: 1, escape: true });
  out.escape = q("edit-confirm").hidden;
  framePosts.length = 0;
  q("edit-discard").click();
  out.discarded = [framePosts.slice(), q("edit-tools").hidden, q("edit-btn").hidden,
    frames() - before];
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


def test_bridge_edit_mode():
    out = run(BRIDGE, served("bridge.js"))
    assert out["ignored"] == [[], [], []]  # other origins and windows are ignored
    assert out["start"] == [[{"ontic": "edit-state", "changes": 0, "editable": 5}, APEX]]
    # Only elements with nothing but text; not inside svg, not empty, not the page's own editor.
    assert out["editable"] == [
        "h1:Title & more", "b:bold", "p:Plain para", "a:A link", "pre:code\nblock"
    ]  # fmt: skip
    assert out["outlined"][0].startswith("1px dashed") and out["outlined"][1] == "2px"
    assert out["outlined"][2:] == ["", "true"]
    assert out["input"] == [[{"ontic": "edit-state", "changes": 1, "editable": 5}, APEX]]
    assert out["click"] == [True, True, 0]  # a link does not navigate, nor reach the bridge
    assert out["clickElsewhere"] is False
    escape = {"ontic": "edit-state", "changes": 1, "editable": 5, "escape": True}
    assert out["escape"] == [True, [[escape, APEX]]]
    assert out["keys"] == [True, False, True, False]  # Enter only in pre; typing stays here
    assert out["save"] == [[{
        "ontic": "edits", "path": "/a/b.html", "changes": [
            {"before": "Title & more", "after": "Title & more!"},
            {"before": "Plain para", "after": "Plain paragraph"},
        ],
    }, APEX]]  # fmt: skip
    assert out["saved"] == ["Title & more!", None, ""]  # the new text stays on screen
    assert out["heldClick"] is True  # until the new version replaces the page
    assert out["resume"] == [[{"ontic": "edit-state", "changes": 2, "editable": 5}, APEX]]
    assert out["resumed"] == 5
    assert out["cancel"] == []
    assert out["restored"] == ["Title & more", "Plain para", 0, "true", ""]
    assert out["clickAfter"] == [True, [[{"ontic": "open", "url": f"{APEX}/other/"}, APEX]]]
    (message, origin), *_ = out["tooLong"]
    assert message["changes"] == [] and "too long" in message["error"]


def test_bar_edit_flow():
    out = run(BAR, served("bar.js"), ROLE="owner", VIEWING=None)
    assert (out["canEdit"], out["tools"]) == (True, True)
    assert out["start"] == [[{"ontic": "edit-mode", "on": True}, CONTENT]]
    assert out["editing"] == [True, False, True, (
        "Text only. Saved as a new version; older versions stay in the title menu."
    )]  # fmt: skip
    assert out["count"] == "Editing: 2 changes"
    assert out["saving"] == [
        [[{"ontic": "edit-mode", "on": False, "save": True}, CONTENT]], "Saving…", True
    ]  # fmt: skip
    assert out["fetch"] == [[
        "/_api/pages/report/edits", "POST",
        {"version": "v1", "path": "/", "changes": [{"before": "a", "after": "b"}]},
    ]]  # fmt: skip
    assert out["saved"] == [True, False, False, 1]  # the new version is loading in a frame
    version, error, panel_hidden, posts, count = out["refused"]
    assert version == "v2" and error == "a newer version was published" and not panel_hidden
    assert posts == [[{"ontic": "edit-mode", "on": True}, CONTENT]]  # back to editing
    assert count == "Editing: 1 change"
    assert out["held"] == 0
    assert out["confirm"] == [False, False, "Discard 1 change?Keep editingDiscard"]
    assert out["kept"] == [True, False]
    assert out["escape"] is False
    posts, tools_hidden, edit_hidden, new_frames = out["discarded"]
    assert posts == [[{"ontic": "edit-mode", "on": False}, CONTENT]]
    assert (tools_hidden, edit_hidden) == (True, False)
    assert new_frames == 1  # the version published meanwhile fades in now


@pytest.mark.parametrize("role, viewing", [("viewer", None), ("owner", "v0")])
def test_bar_edit_only_for_the_owner_on_the_current_version(role, viewing):
    out = run(BAR, served("bar.js"), ROLE=role, VIEWING=viewing)
    assert out == {"canEdit": False, "tools": True}
