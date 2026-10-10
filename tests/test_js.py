"""The bridge and the bar in node, with just enough of a browser around them: a link in a page to
the apex is handed to the bar, which opens it in the whole tab, only on its own origin."""

import json
import shutil
import subprocess
from importlib.resources import files

import pytest

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(not NODE, reason="needs node")
STATIC = files("ontic_pages") / "static"
APEX = "https://pages.test"
CONTENT = "https://report.pages.test"

BRIDGE = """
const vm = require("vm");
const posted = [], listeners = {};
const parent = { postMessage: (message, origin) => posted.push([message, origin]) };
const window = { parent, top: parent, scrollY: 0,
  addEventListener: (type, f) => (listeners[type] = listeners[type] || []).push(f) };
const location = new URL(CONTENT + "/a/b.html");
const document = { readyState: "complete", title: "t", querySelector: () => null,
  addEventListener() {} };
vm.runInNewContext(SOURCE, { window, document, location, history: {}, URL, setTimeout });
function link(href, attrs) {
  attrs = attrs || {};
  return { href: new URL(href, location.href).href, closest() { return this; },
    getAttribute: (k) => (k in attrs ? attrs[k] : null), hasAttribute: (k) => k in attrs };
}
function click(href, attrs, extra) {
  posted.length = 0;
  const event = Object.assign({ defaultPrevented: false, button: 0, target: link(href, attrs),
    preventDefault() { this.defaultPrevented = true; } }, extra || {});
  listeners.click.forEach((f) => f(event));
  return { prevented: event.defaultPrevented, posted: posted.slice() };
}
console.log(JSON.stringify([
  click(APEX + "/other/"),
  click("/x.html"),
  click("https://evil.test/"),
  click(APEX + "/other/", {}, { ctrlKey: true }),
  click(APEX + "/other/", {}, { button: 1 }),
  click(APEX + "/other/", { target: "_blank" }),
  click(APEX + "/other/", { target: "_top" }),
  click(APEX + "/other/", { download: "" }),
  click(APEX + "/other/", {}, { defaultPrevented: true }),
]));
"""

BAR = """
const vm = require("vm");
const assigned = [], listeners = {};
const frame = { contentWindow: { postMessage() {} }, classList: { add() {} } };
const facts = { page: { name: "report", content_origin: CONTENT, versions: [], current: "v" },
  view: { path: "/", version: null } };
const document = {
  getElementById: (id) => id === "ontic-facts" ? { textContent: JSON.stringify(facts) }
    : id === "frame" ? frame : null,
  addEventListener() {},
};
const window = { addEventListener: (type, f) => (listeners[type] = listeners[type] || []).push(f) };
const location = { origin: APEX, href: APEX + "/report/", assign: (u) => assigned.push(u) };
vm.runInNewContext(SOURCE, { window, document, location, history: {}, URL,
  setTimeout: () => 0, clearTimeout() {} });
function message(data, origin, source) {
  assigned.length = 0;
  listeners.message.forEach((f) => f({ data, origin: origin || CONTENT,
    source: source || frame.contentWindow }));
  return assigned.slice();
}
console.log(JSON.stringify([
  message({ ontic: "open", url: APEX + "/other/?a=1#b" }),
  message({ ontic: "open", url: "https://evil.test/" }),
  message({ ontic: "open", url: "javascript:alert(1)" }),
  message({ ontic: "open", url: APEX + "/x/" }, "https://other.pages.test"),
  message({ ontic: "open", url: APEX + "/x/" }, CONTENT, {}),
  message({ ontic: "open", url: 7 }),
]));
"""


def run(script: str, source: str):
    head = f"const APEX = {json.dumps(APEX)}, CONTENT = {json.dumps(CONTENT)};\n"
    head += f"const SOURCE = {json.dumps(source)};\n"
    out = subprocess.run([NODE, "-e", head + script], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_bridge_hands_apex_links_to_the_bar():
    source = (STATIC / "bridge.js").read_text().replace("__APEX__", json.dumps(APEX))
    results = run(BRIDGE, source)
    opened = {"prevented": True, "posted": [[{"ontic": "open", "url": f"{APEX}/other/"}, APEX]]}
    left = {"prevented": False, "posted": []}
    assert results[0] == opened  # a plain click: the bar opens it
    assert results[1:6] == [left] * 5  # the page's own links, elsewhere, new tabs and windows
    assert results[6] == opened  # target=_top cannot leave the frame by itself
    assert results[7] == left  # a download
    assert results[8] == {"prevented": True, "posted": []}  # the page handled it


READY = """
const vm = require("vm");
const posted = [];
const parent = { postMessage: (message, origin) => posted.push([message, origin]) };
const window = { parent, top: parent, scrollY: 0, addEventListener() {} };
const location = new URL(CONTENT + "/a/b.html");
const currentScript = { getAttribute: (k) => (k === "data-version" ? SERVED : null) };
const document = { readyState: "complete", title: "t", querySelector: () => null,
  addEventListener() {}, currentScript };
vm.runInNewContext(SOURCE, { window, document, location, history: {}, URL, setTimeout });
console.log(JSON.stringify(posted));
"""


@pytest.mark.parametrize(
    "served, said",
    [("20261010T120000Z", "20261010T120000Z"), ('x"><script>', ""), (None, "")],
)
def test_bridge_says_which_version_it_was_served_from(served, said):
    source = (STATIC / "bridge.js").read_text().replace("__APEX__", json.dumps(APEX))
    posted = run(f"const SERVED = {json.dumps(served)};\n" + READY, source)
    assert posted == [
        [{"ontic": "ready", "version": said}, APEX],
        [{"ontic": "nav", "path": "/a/b.html", "title": "t", "version": said}, APEX],
    ]


def test_bar_opens_only_its_own_origin():
    results = run(BAR, (STATIC / "bar.js").read_text())
    assert results == [[f"{APEX}/other/?a=1#b"], [], [], [], [], []]
