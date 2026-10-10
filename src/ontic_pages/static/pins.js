// Comment pins inside a page: the second part of the bridge (the gateway serves bridge.js and
// this file as one script, added to a page's HTML only in the bar's frame). Comments attach to
// elements: in comment mode the element under the pointer is outlined (with a small label naming
// it), and a click on it becomes an anchor (which element, the point within it) that goes to the
// bar. The pins the bar sends are drawn over the page and follow their elements while it
// scrolls, resizes or changes; pins that cannot be placed are reported back. The element of the
// open thread (the active pin) is outlined too, and so is a pin's element while the pointer is
// on the pin or on its card in the bar. It never sees comment text or anyone's email: a pin is
// an id, an initial, a color, its anchor and two flags. Nothing is drawn until the bar sends pins
// or turns comment mode on; then everything lives in one element at the end of the document, in
// a closed shadow root at the highest z-index, so the page's styles neither reach the pins nor
// are touched by them. Styles are set through the DOM, which a page's own policy does not block.
//
// From the bar: comment-mode {on}, pins {pins, seq}, pin-focus {id}, highlight {id or null}.
// To the bar: comment-at {anchor, point}, pin-open {id, point}, orphans {ids, seq},
// comment-escape. Like the bridge, it posts to the apex only and listens only to the apex parent.
(function () {
  "use strict";
  var APEX = __APEX__;
  if (window.parent === window || window.parent !== window.top) return;

  var MAX_DEPTH = 8;
  var SNIPPET = 60;
  var LABEL = 32;
  var MAX_PINS = 500;
  var HUGE = 0.8; // an element over this share of the viewport is a wrapper, not a target
  var ACCENT = "#2f5bd3";
  var VERSION = /^\/_v\/\d{8}T\d{6}Z(?=\/)/;
  var COLOR = /^#[0-9a-fA-F]{6}$/;
  var mode = false;
  var pins = []; // [{id, initial, color, anchor, resolved, fallback, active}]
  var nodes = {}; // id -> pin element
  var host = null, layer = null, capture = null;
  var boxes = {}; // selected, hover: outline boxes; label: the hover box's name
  var pointer = null; // {x, y}: where the pointer is in comment mode
  var hoverId = null; // a pin whose element is outlined (the pointer on the pin, or its card)
  var selected = null; // the element of the active pin, from the last place()
  var lastOrphans = null;
  var seq = 0; // the bar's number for the pins message being answered
  var scheduled = false, boxesScheduled = false;

  function send(message) {
    try {
      window.parent.postMessage(message, APEX);
    } catch (error) { /* not inside the bar */ }
  }

  function css(node, styles) {
    Object.keys(styles).forEach(function (key) { node.style.setProperty(key, styles[key]); });
    return node;
  }

  function part(name, styles) {
    var node = css(document.createElement("div"), styles);
    node.setAttribute("data-part", name);
    return node;
  }

  function overlay() {
    if (host && host.isConnected) return;
    host = css(document.createElement("ontic-comments"), {
      all: "initial", position: "fixed", left: "0", top: "0", width: "100%", height: "100%",
      overflow: "hidden", "pointer-events": "none", "z-index": "2147483647"
    });
    var root = host.attachShadow ? host.attachShadow({ mode: "closed" }) : host;
    capture = part("capture", {
      position: "absolute", left: "0", top: "0", width: "100%", height: "100%",
      cursor: "pointer", "pointer-events": "auto", display: mode ? "block" : "none"
    });
    capture.addEventListener("click", onCapture);
    capture.addEventListener("pointermove", onMove);
    capture.addEventListener("pointerleave", function () { pointer = null; scheduleBoxes(); });
    var outline = {
      position: "absolute", display: "none", "box-sizing": "border-box",
      "pointer-events": "none", border: "2px solid " + ACCENT
    };
    boxes.selected = part("selected", outline);
    boxes.selected.style.setProperty("background", "rgba(47, 91, 211, .08)");
    boxes.hover = part("hover", outline);
    boxes.label = part("label", {
      position: "absolute", display: "none", "pointer-events": "none", "max-width": "280px",
      padding: "1px 6px", "border-radius": "4px", background: ACCENT, color: "#fff",
      font: "500 11px/16px system-ui,-apple-system,'Segoe UI',Roboto,sans-serif",
      "white-space": "nowrap", overflow: "hidden", "text-overflow": "ellipsis"
    });
    layer = part("pins", {
      position: "absolute", left: "0", top: "0", width: "100%", height: "100%"
    });
    [capture, boxes.selected, boxes.hover, boxes.label, layer].forEach(function (node) {
      root.appendChild(node);
    });
    nodes = {};
    document.documentElement.appendChild(host);
  }

  // ---- anchors -------------------------------------------------------------------------------

  function snippetOf(element) {
    var text = element.textContent || (element.getAttribute && (element.getAttribute("alt")
      || element.getAttribute("aria-label"))) || "";
    return text.slice(0, 2000).replace(/\s+/g, " ").trim().slice(0, SNIPPET);
  }

  function tagOf(element) {
    return String(element.localName || element.tagName || "").toLowerCase();
  }

  // What the label says: the tag name and the start of the element's text.
  function describe(element) {
    var text = snippetOf(element);
    if (text.length > LABEL) text = text.slice(0, LABEL - 1) + "…";
    return tagOf(element) + (text ? "  " + text : "");
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
    function share(offset, size) { return size > 0 ? Math.min(1, Math.max(0, offset / size)) : 0.5; }
    return {
      path: pagePath(),
      selector: selectorFor(element),
      tag: tagOf(element),
      fx: share(x - box.left, box.width),
      fy: share(y - box.top, box.height),
      snippet: snippetOf(element),
      x: Math.max(0, x + window.scrollX),
      y: Math.max(0, y + window.scrollY)
    };
  }

  // The page's element at a point, under the capture layer.
  function hitAt(x, y) {
    if (!document.elementFromPoint) return null;
    if (capture) capture.style.setProperty("pointer-events", "none");
    var element = document.elementFromPoint(x, y);
    if (capture) capture.style.setProperty("pointer-events", "auto");
    return element;
  }

  function page(element) {
    return element && element.nodeType === 1 && element !== host
      && element !== document.documentElement && element !== document.body;
  }

  // The element a comment at this point attaches to: the one under the pointer, however small,
  // but not the document itself, our overlay, or a wrapper covering most of the viewport (there
  // is no way down from it to what the pointer means).
  function targetAt(x, y) {
    var element = hitAt(x, y);
    if (!page(element)) return null;
    var box = element.getBoundingClientRect();
    var width = window.innerWidth || 0, height = window.innerHeight || 0;
    var seenW = Math.max(0, Math.min(box.right, width) - Math.max(box.left, 0));
    var seenH = Math.max(0, Math.min(box.bottom, height) - Math.max(box.top, 0));
    if (width > 0 && height > 0 && seenW * seenH > HUGE * width * height) return null;
    return element;
  }

  function onMove(event) {
    pointer = { x: event.clientX, y: event.clientY };
    scheduleBoxes();
  }

  function onCapture(event) {
    event.preventDefault();
    event.stopPropagation();
    var x = event.clientX, y = event.clientY;
    // A wrapper too big to outline still takes the comment, at the point clicked.
    var target = targetAt(x, y) || hitAt(x, y);
    if (!page(target)) target = document.body;
    if (!target) return;
    pointer = null;
    send({ ontic: "comment-at", anchor: anchorFor(target, x, y), point: { x: x, y: y } });
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

  function pinById(id) {
    return pins.filter(function (p) { return p.id === id; })[0] || null;
  }

  // ---- outlines ------------------------------------------------------------------------------

  // The element's corner radius, a little larger since the box sits just outside it.
  function radius(element) {
    var value = "";
    try { value = window.getComputedStyle(element).borderTopLeftRadius || ""; } catch (error) { /* none */ }
    var px = /^(\d+(?:\.\d+)?)px$/.exec(value);
    return px ? (parseFloat(px[1]) + 3) + "px" : "3px";
  }

  function outline(box, element) {
    if (!element || element.isConnected === false) {
      box.style.setProperty("display", "none");
      return null;
    }
    var r = element.getBoundingClientRect();
    if (!(r.width > 0 || r.height > 0)) {
      box.style.setProperty("display", "none");
      return null;
    }
    css(box, {
      display: "block", left: Math.round(r.left - 3) + "px", top: Math.round(r.top - 3) + "px",
      width: Math.round(r.width + 6) + "px", height: Math.round(r.height + 6) + "px",
      "border-radius": radius(element)
    });
    return r;
  }

  function drawBoxes() {
    boxesScheduled = false;
    if (!host) return;
    var hovered = null;
    if (mode && pointer) hovered = targetAt(pointer.x, pointer.y);
    else if (hoverId) {
      var pin = pinById(hoverId);
      var point = pin && locate(pin.anchor, pin.fallback);
      hovered = point && point.element;
    }
    outline(boxes.selected, selected);
    var r = outline(boxes.hover, hovered === selected ? null : hovered);
    var label = boxes.label;
    if (!r || !mode) { label.style.setProperty("display", "none"); return; }
    label.textContent = describe(hovered);
    css(label, {
      display: "block", left: Math.round(Math.max(0, r.left - 3)) + "px",
      top: Math.round(r.top - 23 >= 0 ? r.top - 23 : r.bottom + 5) + "px"
    });
  }

  function scheduleBoxes() {
    if (boxesScheduled) return;
    boxesScheduled = true;
    (window.requestAnimationFrame || setTimeout)(drawBoxes);
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
      node.addEventListener("pointerenter", function () {
        pointer = null;
        hoverId = pin.id;
        scheduleBoxes();
      });
      node.addEventListener("pointerleave", function () {
        if (hoverId === pin.id) hoverId = null;
        scheduleBoxes();
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
    selected = null;
    if (!pins.length) {
      reportOrphans([]);
      drawBoxes();
      return;
    }
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
      if (pin.active && page(point.element)) selected = point.element;
      node.style.display = "block";
      node.style.left = Math.round(point.x) + "px";
      node.style.top = Math.round(point.y - 24) + "px";
    });
    reportOrphans(orphans);
    drawBoxes();
  }

  function busy() { return pins.length || mode || hoverId; }

  function schedule() {
    if (scheduled || !busy()) return;
    scheduled = true;
    (window.requestAnimationFrame || setTimeout)(place);
  }

  function setMode(on) {
    mode = on;
    pointer = null;
    if (!on && !host) return;
    overlay();
    capture.style.display = mode ? "block" : "none";
    drawBoxes();
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
    if (hoverId && !kept[hoverId]) hoverId = null;
    lastOrphans = null; // the bar waits for one answer to each pins message
    place();
  }

  // Open a thread from the bar's list or a link: its element comes into view (outlined, as the
  // active pin once the bar has opened it), and the bar hears where the pin is.
  function focusPin(id) {
    var pin = pinById(id);
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

  function highlight(id) {
    hoverId = typeof id === "string" && pinById(id) ? id : null;
    if (hoverId) overlay();
    if (host) drawBoxes();
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
    else if (message.ontic === "highlight") highlight(message.id);
  });
  // Escape with the focus in the page: the bar cannot hear it, so it is passed on.
  window.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    if (mode || pins.some(function (p) { return p.active; })) send({ ontic: "comment-escape" });
  }, true);
  window.addEventListener("scroll", schedule, { capture: true, passive: true });
  window.addEventListener("resize", schedule);
  window.addEventListener("load", schedule);
  if (window.ResizeObserver) {
    var observer = new ResizeObserver(schedule);
    var watch = function () {
      observer.observe(document.documentElement);
      if (document.body) observer.observe(document.body);
    };
    if (document.body) watch();
    else document.addEventListener("DOMContentLoaded", watch);
  }
  // The page changing under the pins (content added, text or classes changed): place them again.
  // Our overlay sits outside <body>, so drawing it is not a change seen here.
  if (window.MutationObserver) {
    var changes = new MutationObserver(schedule);
    var watchBody = function () {
      if (document.body) {
        changes.observe(document.body, { childList: true, subtree: true, attributes: true,
                                         characterData: true });
      }
    };
    if (document.body) watchBody();
    else document.addEventListener("DOMContentLoaded", watchBody);
  }
})();
