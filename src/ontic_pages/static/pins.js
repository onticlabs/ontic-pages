// Comment pins inside a page: the second part of the bridge (the gateway serves bridge.js and
// this file as one script, added to a page's HTML only in the bar's frame). In comment mode a
// click on the page becomes an anchor (where on the page it points) that goes to the bar. The
// pins the bar sends are drawn over the page and kept in place while it scrolls and resizes;
// pins that cannot be placed are reported back. It never sees comment text or anyone's email: a
// pin is an id, an initial, a color, its anchor and two flags. Nothing is drawn until the bar
// sends pins or turns comment mode on; then everything lives in one element at the end of the
// document, in a closed shadow root at the highest z-index, so the page's styles neither reach
// the pins nor are touched by them. Styles are set through the DOM, which a page's own policy
// does not block.
//
// From the bar: comment-mode {on}, pins {pins, seq}, pin-focus {id}.
// To the bar: comment-at {anchor, point}, pin-open {id, point}, orphans {ids, seq},
// comment-escape. Like the bridge, it posts to the apex only and listens only to the apex parent.
(function () {
  "use strict";
  var APEX = __APEX__;
  if (window.parent === window || window.parent !== window.top) return;

  var MAX_DEPTH = 8;
  var SNIPPET = 60;
  var MAX_PINS = 500;
  var VERSION = /^\/_v\/\d{8}T\d{6}Z(?=\/)/;
  var COLOR = /^#[0-9a-fA-F]{6}$/;
  var mode = false;
  var pins = []; // [{id, initial, color, anchor, resolved, fallback, active}]
  var nodes = {}; // id -> pin element
  var host = null, layer = null, capture = null;
  var lastOrphans = null;
  var seq = 0; // the bar's number for the pins message being answered
  var scheduled = false;

  function send(message) {
    try {
      window.parent.postMessage(message, APEX);
    } catch (error) { /* not inside the bar */ }
  }

  function css(node, styles) {
    Object.keys(styles).forEach(function (key) { node.style.setProperty(key, styles[key]); });
    return node;
  }

  function overlay() {
    if (host && host.isConnected) return;
    host = css(document.createElement("ontic-comments"), {
      all: "initial", position: "fixed", left: "0", top: "0", width: "100%", height: "100%",
      overflow: "hidden", "pointer-events": "none", "z-index": "2147483647"
    });
    var root = host.attachShadow ? host.attachShadow({ mode: "closed" }) : host;
    capture = css(document.createElement("div"), {
      position: "absolute", left: "0", top: "0", width: "100%", height: "100%",
      cursor: "crosshair", "pointer-events": "auto", display: mode ? "block" : "none"
    });
    capture.addEventListener("click", onCapture);
    layer = css(document.createElement("div"), {
      position: "absolute", left: "0", top: "0", width: "100%", height: "100%"
    });
    root.appendChild(capture);
    root.appendChild(layer);
    nodes = {};
    document.documentElement.appendChild(host);
  }

  // ---- anchors -------------------------------------------------------------------------------

  function snippetOf(element) {
    var text = element.textContent || (element.getAttribute && (element.getAttribute("alt")
      || element.getAttribute("aria-label"))) || "";
    return text.slice(0, 2000).replace(/\s+/g, " ").trim().slice(0, SNIPPET);
  }

  function escapeId(id) {
    return window.CSS && CSS.escape ? CSS.escape(id) : id.replace(/[^\w-]/g, "\\$&");
  }

  // A CSS path to `element`: a unique id where there is one, else tag and nth-of-type, at most
  // MAX_DEPTH levels.
  function selectorFor(element) {
    var parts = [];
    var node = element;
    while (node && node.nodeType === 1 && node !== document.documentElement
           && parts.length < MAX_DEPTH) {
      if (node.id) {
        var byId = "#" + escapeId(node.id);
        try {
          if (document.querySelectorAll(byId).length === 1) { parts.unshift(byId); break; }
        } catch (error) { /* an id no selector can name: use the tag */ }
      }
      var index = 1;
      for (var s = node.previousElementSibling; s; s = s.previousElementSibling) {
        if (s.tagName === node.tagName) index += 1;
      }
      parts.unshift(node.tagName.toLowerCase() + ":nth-of-type(" + index + ")");
      node = node.parentElement;
    }
    return parts.join(" > ");
  }

  function pagePath() {
    return location.pathname.replace(VERSION, "") + location.search;
  }

  function anchorFor(element, x, y) {
    var box = element.getBoundingClientRect();
    function part(offset, size) { return size > 0 ? Math.min(1, Math.max(0, offset / size)) : 0.5; }
    return {
      path: pagePath(),
      selector: selectorFor(element),
      fx: part(x - box.left, box.width),
      fy: part(y - box.top, box.height),
      snippet: snippetOf(element),
      x: Math.max(0, x + window.scrollX),
      y: Math.max(0, y + window.scrollY)
    };
  }

  function onCapture(event) {
    event.preventDefault();
    event.stopPropagation();
    capture.style.display = "none";
    var target = document.elementFromPoint(event.clientX, event.clientY);
    capture.style.display = mode ? "block" : "none";
    if (!target || target === host || target === document.documentElement) target = document.body;
    if (!target) return;
    send({ ontic: "comment-at", anchor: anchorFor(target, event.clientX, event.clientY),
           point: { x: event.clientX, y: event.clientY } });
  }

  // Where an anchor is now, in viewport coordinates, or null: on the element its selector names
  // while the element's text still matches, else at the document position it was made at (only
  // with `fallback`, and only inside the document).
  function locate(anchor, fallback) {
    var element = null;
    if (anchor.selector) {
      try { element = document.querySelector(anchor.selector); } catch (error) { element = null; }
    }
    if (element && anchor.snippet && snippetOf(element) !== anchor.snippet) element = null;
    if (element) {
      var box = element.getBoundingClientRect();
      if (box.width > 0 || box.height > 0) {
        return { x: box.left + anchor.fx * box.width, y: box.top + anchor.fy * box.height,
                 element: element };
      }
    }
    if (!fallback || typeof anchor.x !== "number" || typeof anchor.y !== "number") return null;
    var doc = document.documentElement, body = document.body || doc;
    var width = Math.max(doc.scrollWidth, body.scrollWidth);
    var height = Math.max(doc.scrollHeight, body.scrollHeight);
    if (anchor.x > width || anchor.y > height) return null;
    return { x: anchor.x - window.scrollX, y: anchor.y - window.scrollY, element: null };
  }

  // ---- pins ----------------------------------------------------------------------------------

  function pinNode(pin) {
    var node = nodes[pin.id];
    if (!node) {
      node = css(document.createElement("div"), {
        position: "absolute", width: "24px", height: "24px", "box-sizing": "border-box",
        "border-radius": "12px 12px 12px 2px", border: "2px solid #fff",
        "box-shadow": "0 2px 8px rgba(0,0,0,.28)", color: "#fff",
        font: "600 11px/20px system-ui,-apple-system,'Segoe UI',Roboto,sans-serif",
        "text-align": "center", cursor: "pointer", "pointer-events": "auto",
        "user-select": "none", transition: "transform .12s ease"
      });
      node.setAttribute("role", "button");
      node.setAttribute("aria-label", "Comment");
      node.addEventListener("click", function (event) {
        event.preventDefault();
        event.stopPropagation();
        var box = node.getBoundingClientRect();
        send({ ontic: "pin-open", id: pin.id, point: { x: box.right, y: box.top } });
      });
      layer.appendChild(node);
      nodes[pin.id] = node;
    }
    node.textContent = pin.initial;
    node.style.setProperty("background", COLOR.test(pin.color || "") ? pin.color : "#d97706");
    node.style.setProperty("opacity", pin.resolved ? "0.55" : "1");
    node.style.setProperty("transform", pin.active ? "scale(1.18)" : "none");
    node.style.setProperty("z-index", pin.active ? "1" : "0");
    return node;
  }

  function reportOrphans(orphans) {
    var key = orphans.join(",");
    if (key === lastOrphans) return;
    lastOrphans = key;
    send({ ontic: "orphans", ids: orphans, seq: seq });
  }

  function place() {
    scheduled = false;
    if (!pins.length) { reportOrphans([]); return; }
    overlay();
    var orphans = [];
    pins.forEach(function (pin) {
      var node = pinNode(pin);
      var point = locate(pin.anchor, pin.fallback);
      if (!point) {
        node.style.display = "none";
        if (pin.id !== "draft") orphans.push(pin.id);
        return;
      }
      node.style.display = "block";
      node.style.left = Math.round(point.x) + "px";
      node.style.top = Math.round(point.y - 24) + "px";
    });
    reportOrphans(orphans);
  }

  function schedule() {
    if (scheduled) return;
    scheduled = true;
    (window.requestAnimationFrame || setTimeout)(place);
  }

  function setMode(on) {
    mode = on;
    if (!on && !host) return;
    overlay();
    capture.style.display = mode ? "block" : "none";
  }

  function setPins(list) {
    var kept = {};
    pins = [];
    (Array.isArray(list) ? list : []).slice(0, MAX_PINS).forEach(function (pin) {
      if (!pin || typeof pin.id !== "string" || !pin.anchor || typeof pin.anchor !== "object") {
        return;
      }
      pins.push({ id: pin.id, initial: String(pin.initial || "?").slice(0, 2), color: pin.color,
                  anchor: pin.anchor, resolved: !!pin.resolved, fallback: pin.fallback === true,
                  active: !!pin.active });
      kept[pin.id] = true;
    });
    Object.keys(nodes).forEach(function (id) {
      if (!kept[id]) { nodes[id].remove(); delete nodes[id]; }
    });
    lastOrphans = null; // the bar waits for one answer to each pins message
    place();
  }

  function focusPin(id) {
    var pin = pins.filter(function (p) { return p.id === id; })[0];
    if (!pin) return;
    var point = locate(pin.anchor, pin.fallback);
    if (!point) { lastOrphans = null; place(); return; }
    if (point.element && point.element.scrollIntoView) {
      point.element.scrollIntoView({ block: "center", inline: "nearest" });
    } else {
      window.scrollTo(window.scrollX, Math.max(0, window.scrollY + point.y - window.innerHeight / 2));
    }
    place();
    var node = nodes[id];
    if (!node || node.style.display === "none") return;
    var box = node.getBoundingClientRect();
    send({ ontic: "pin-open", id: id, point: { x: box.right, y: box.top } });
  }

  window.addEventListener("message", function (event) {
    if (event.origin !== APEX || event.source !== window.parent) return;
    var message = event.data;
    if (!message || typeof message !== "object") return;
    if (message.ontic === "comment-mode") setMode(message.on === true);
    else if (message.ontic === "pins") {
      seq = typeof message.seq === "number" ? message.seq : 0;
      setPins(message.pins);
    } else if (message.ontic === "pin-focus" && typeof message.id === "string") focusPin(message.id);
  });
  // Escape with the focus in the page: the bar cannot hear it, so it is passed on.
  window.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    if (mode || pins.some(function (p) { return p.active; })) send({ ontic: "comment-escape" });
  }, true);
  window.addEventListener("scroll", function () { if (pins.length) schedule(); },
                          { capture: true, passive: true });
  window.addEventListener("resize", function () { if (pins.length) schedule(); });
  window.addEventListener("load", function () { if (pins.length) schedule(); });
  if (window.ResizeObserver) {
    var observer = new ResizeObserver(function () { if (pins.length) schedule(); });
    var watch = function () {
      observer.observe(document.documentElement);
      if (document.body) observer.observe(document.body);
    };
    if (document.body) watch();
    else document.addEventListener("DOMContentLoaded", watch);
  }
})();
