// Edit text in place, the page's side. Served as part of the bridge (after bridge.js), so it runs
// only in a page shown in the bar's frame, and talks only to the apex and the parent window.
//
// For the page's owner on the current version the bar turns editing on as the page loads, and
// it stays on: an element whose children are all text (paragraphs, headings, list items, cells,
// ...) becomes editable as plain text when the pointer comes onto it, with a subtle outline
// only while hovered or focused. Never one that is or sits inside something interactive (links,
// buttons, form fields, the page's own editors, elements with a role, a tabindex, onclick or a
// pointer cursor), nor inside scripts, styles, svg, canvas or templates: those keep working as
// the page made them. A text counts as changed only after an `input` event in it, so text the
// page's own scripts update is never counted.
//
// From the bar: edit-mode {on} turns editing on or off (the changes so far stay; while comment
// mode is on, editing is suspended as well), {discard: true} first puts every original text
// back, {on: false, save: true} answers edits {path, changes: [{before, after}]} and stops
// editing, leaving the new text on screen until the saved version replaces this page. To the
// bar: edit-state {changes} whenever the count changes or editing starts, with save: true for
// Cmd/Ctrl+S in the page.
(function () {
  "use strict";
  var APEX = __APEX__;
  if (window.parent === window || window.parent !== window.top) return;

  var TAGS = {
    P: 1, H1: 1, H2: 1, H3: 1, H4: 1, H5: 1, H6: 1, LI: 1, TD: 1, TH: 1, DT: 1, DD: 1,
    FIGCAPTION: 1, BLOCKQUOTE: 1, CAPTION: 1, SPAN: 1, LEGEND: 1, SMALL: 1, STRONG: 1, EM: 1,
    B: 1, I: 1, U: 1, S: 1, MARK: 1, CITE: 1, Q: 1, SUB: 1, SUP: 1, ABBR: 1, TIME: 1, CODE: 1,
    PRE: 1, DIV: 1
  };
  // Never editable, nor anything inside them.
  var SKIP = {
    SCRIPT: 1, STYLE: 1, SVG: 1, CANVAS: 1, TEMPLATE: 1, NOSCRIPT: 1, MATH: 1, IFRAME: 1,
    A: 1, BUTTON: 1, SUMMARY: 1, LABEL: 1, SELECT: 1, OPTION: 1, INPUT: 1, TEXTAREA: 1
  };
  var ROLES = new RegExp("^(button|link|checkbox|radio|switch|tab|menuitem|menuitemcheckbox|" +
    "menuitemradio|option|combobox|textbox|slider|spinbutton|treeitem)$");
  var MAX_CHANGES = 500, MAX_TEXT = 20000, MAX_BYTES = 60000; // the gateway's limits
  var HOVER = "1px solid rgba(47, 91, 211, .45)", FOCUS = "2px solid rgba(47, 91, 211, .85)";

  var items = []; // {el, before, outline, offset, touched}: kept until a discard or a new page
  var enabled = false; // the bar said on
  var commenting = false; // comment mode: clicks make comments, nothing is editable
  var mode = "";
  var sent = -1; // the count last told to the bar

  function send(message) {
    try {
      window.parent.postMessage(message, APEX);
    } catch (error) { /* not inside the bar */ }
  }

  function editMode() {
    if (mode) return mode;
    mode = "true";
    try {
      var probe = document.createElement("div");
      probe.contentEditable = "plaintext-only";
      if (probe.contentEditable === "plaintext-only") mode = "plaintext-only";
    } catch (error) { /* an older browser: "true", pasting plain text below */ }
    return mode;
  }

  function active() { return enabled && !commenting; }

  function item(node) {
    for (var i = 0; i < items.length; i++) {
      if (items[i].el === node) return items[i];
    }
    return null;
  }

  // The item an event happened in: the element itself, or (typing) a node inside it.
  function itemOf(node) {
    for (var n = node; n; n = n.parentNode) {
      var it = n.nodeType === 1 ? item(n) : null;
      if (it) return it;
    }
    return null;
  }

  function textOnly(el) {
    var nodes = el.childNodes;
    if (!nodes || !nodes.length) return false;
    for (var i = 0; i < nodes.length; i++) {
      if (nodes[i].nodeType !== 3) return false;
    }
    return /\S/.test(el.textContent);
  }

  function tag(el) { return String(el.tagName || "").toUpperCase(); }

  // Something the page uses as a control (or its own editor), or inside one.
  function interactive(el) {
    for (var n = el; n && n.nodeType === 1; n = n.parentNode) {
      if (SKIP[tag(n)]) return true;
      if (ROLES.test(String(n.getAttribute("role") || "").trim().toLowerCase())) return true;
      if (n.hasAttribute("onclick")) return true;
      // A tabindex makes a control; but -1 on a container (a skip link's target) does not.
      var tabindex = n.getAttribute("tabindex");
      if (tabindex !== null && (n === el || tabindex.trim() !== "-1")) return true;
      if (n.hasAttribute("contenteditable") && !item(n)) return true;
    }
    if (window.getComputedStyle) {
      try {
        if (window.getComputedStyle(el).cursor === "pointer") return true;
      } catch (error) { /* not an element the page shows */ }
    }
    return false;
  }

  function eligible(el) {
    return !!el && el.nodeType === 1 && TAGS[tag(el)] === 1 && el !== document.body
      && textOnly(el) && !interactive(el);
  }

  function editable(it, on) {
    if (on) it.el.setAttribute("contenteditable", editMode());
    else it.el.removeAttribute("contenteditable");
  }

  // The element under the pointer becomes editable (once; it stays so while editing is on).
  function adopt(el) {
    var it = item(el);
    if (!it) {
      if (!eligible(el)) return null;
      it = { el: el, before: el.textContent, outline: el.style.outline,
             offset: el.style.outlineOffset, touched: false };
      items.push(it);
    }
    if (it.el.getAttribute("contenteditable") === null) editable(it, true);
    return it;
  }

  function look(it, outline) {
    it.el.style.outline = outline === null ? it.outline : outline;
    it.el.style.outlineOffset = outline === null ? it.offset : "2px";
  }

  // What the element says now. Browsers type a no-break space for a trailing or double space;
  // it was a plain one unless the original had any.
  function now(it) {
    var text = it.el.textContent;
    return it.before.indexOf(" ") < 0 ? text.replace(/ /g, " ") : text;
  }

  function count() {
    var n = 0;
    items.forEach(function (it) { if (it.touched && now(it) !== it.before) n++; });
    return n;
  }

  function state(force, save) {
    var n = count();
    if (n === sent && !force && !save) return;
    sent = n;
    var message = { ontic: "edit-state", changes: n };
    if (save) message.save = true;
    send(message);
  }

  // On: the texts already taken are editable again at once, the rest as the pointer comes.
  // Off: nothing is editable, untouched texts are forgotten, the changes stay on screen.
  function apply() {
    var on = active();
    var focused = document.activeElement;
    if (!on && focused && item(focused) && focused.blur) focused.blur();
    items = items.filter(function (it) {
      look(it, null);
      editable(it, on);
      return on || it.touched;
    });
  }

  function bytes(text) {
    try { return new TextEncoder().encode(text).length; } catch (error) { return text.length * 3; }
  }

  function edits() {
    var changes = [], error = "";
    items.forEach(function (it) {
      if (!it.touched) return;
      var after = now(it);
      if (after === it.before) return;
      if (it.before.length > MAX_TEXT || after.length > MAX_TEXT) {
        error = "A text is too long to save here (over " + MAX_TEXT + " characters).";
      }
      changes.push({ before: it.before, after: after });
    });
    if (changes.length > MAX_CHANGES) {
      error = "Too many changes for one save (at most " + MAX_CHANGES + "): save some first.";
    } else if (!error && bytes(JSON.stringify(changes)) > MAX_BYTES) {
      error = "Too much changed text for one save: save some first.";
    }
    var message = { ontic: "edits", path: location.pathname, changes: error ? [] : changes };
    if (error) message.error = error;
    return message;
  }

  function discard() {
    items.forEach(function (it) {
      look(it, null);
      editable(it, false);
      if (it.touched && it.el.textContent !== it.before) it.el.textContent = it.before;
    });
    items = [];
  }

  window.addEventListener("message", function (event) {
    if (event.origin !== APEX || event.source !== window.parent) return;
    var message = event.data;
    if (!message || typeof message !== "object") return;
    if (message.ontic === "comment-mode") {
      commenting = message.on === true;
      apply();
      return;
    }
    if (message.ontic !== "edit-mode") return;
    if (message.discard === true) discard();
    if (message.save === true) {
      send(edits());
      enabled = false;
      apply();
      return;
    }
    enabled = message.on === true;
    apply();
    if (enabled) state(true);
  });

  window.addEventListener("pointerover", function (event) {
    if (!active()) return;
    var it = adopt(event.target);
    if (it && document.activeElement !== it.el) look(it, HOVER);
  }, true);
  window.addEventListener("pointerout", function (event) {
    var it = item(event.target);
    if (it && document.activeElement !== it.el) look(it, null);
  }, true);
  window.addEventListener("focusin", function (event) {
    var it = active() && item(event.target);
    if (it) look(it, FOCUS);
  }, true);
  window.addEventListener("focusout", function (event) {
    var it = item(event.target);
    if (it) look(it, null);
  }, true);

  // The text as the user is about to change it, should a script have changed it meanwhile.
  window.addEventListener("beforeinput", function (event) {
    var it = active() && itemOf(event.target);
    if (it && !it.touched) it.before = it.el.textContent;
  }, true);
  window.addEventListener("input", function (event) {
    var it = active() && itemOf(event.target);
    if (!it) return;
    it.touched = true;
    state(false);
  }, true);

  window.addEventListener("keydown", function (event) {
    var key = String(event.key || "").toLowerCase();
    if (key === "s" && (event.metaKey || event.ctrlKey) && !event.altKey && count() > 0) {
      event.preventDefault();
      event.stopPropagation();
      state(false, true);
      return;
    }
    var it = active() && itemOf(event.target);
    if (!it) return;
    event.stopPropagation(); // typing is not the page's keyboard shortcuts
    if (event.key === "Escape") {
      event.preventDefault();
      if (it.el.blur) it.el.blur();
    } else if (event.key === "Enter" && !it.el.closest("pre")) {
      event.preventDefault();
    }
  }, true);

  window.addEventListener("paste", function (event) {
    if (!active() || editMode() === "plaintext-only" || !itemOf(event.target)) return;
    event.preventDefault();
    var text = (event.clipboardData && event.clipboardData.getData("text/plain")) || "";
    document.execCommand("insertText", false, text.replace(/\s*\n\s*/g, " "));
  }, true);

  window.addEventListener("drop", function (event) {
    if (active() && itemOf(event.target)) event.preventDefault();
  }, true);
})();
