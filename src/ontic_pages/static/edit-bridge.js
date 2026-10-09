// Edit text in place, the page's side. Served as part of the bridge (after bridge.js), so it runs
// only in a page shown in the bar's frame, and talks only to the apex and the parent window.
//
// edit-mode {on: true}: elements whose children are all text (paragraphs, headings, list items,
// cells, links, ...; not inside scripts, styles, svg, canvas or templates, not empty) become
// editable as plain text, with a subtle outline, and their original text is kept. edit-state
// {changes, editable} tells the bar how many differ now (and {escape: true} for Escape). Links,
// buttons and the page's own click handlers do nothing while editing.
// edit-mode {on: false, save: true}: answers edits {path, changes: [{before, after}]} and stops
// editing, leaving the new text on screen until the saved version replaces this page;
// edit-mode {on: true} again resumes (after a refused save). edit-mode {on: false}: every
// original text comes back.
(function () {
  "use strict";
  var APEX = __APEX__;
  if (window.parent === window || window.parent !== window.top) return;

  var TAGS = "p,h1,h2,h3,h4,h5,h6,li,td,th,dt,dd,figcaption,blockquote,caption,a,span,label," +
    "button,summary,legend,small,strong,em,b,i,u,s,mark,cite,q,sub,sup,abbr,time,code,pre,div";
  var SKIP = "script,style,svg,canvas,template,noscript,textarea,select,[contenteditable]";
  var ACTIVE = "a,button,summary,label,input,select,option";
  var MAX_CHANGES = 500, MAX_TEXT = 20000, MAX_BYTES = 60000; // the gateway's limits
  var OUTLINE = "1px dashed rgba(47, 91, 211, .55)", FOCUS = "2px solid rgba(47, 91, 211, .85)";

  var items = []; // {el, before, attr, outline, offset}: kept until a cancel or a new page
  var editing = false;
  var mode = "";

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

  function textOnly(el) {
    var nodes = el.childNodes;
    if (!nodes || !nodes.length) return false;
    for (var i = 0; i < nodes.length; i++) {
      if (nodes[i].nodeType !== 3) return false;
    }
    return /\S/.test(el.textContent);
  }

  function collect() {
    var found = [];
    var all = document.body ? document.body.querySelectorAll(TAGS) : [];
    for (var i = 0; i < all.length; i++) {
      var el = all[i];
      if (!textOnly(el) || el.closest(SKIP)) continue;
      found.push({
        el: el, before: el.textContent, attr: el.getAttribute("contenteditable"),
        outline: el.style.outline, offset: el.style.outlineOffset
      });
    }
    return found;
  }

  function item(node) {
    for (var i = 0; i < items.length; i++) {
      if (items[i].el === node) return items[i];
    }
    return null;
  }

  // What the element says now. Browsers type a no-break space for a trailing or double space;
  // it was a plain one unless the original had any.
  function now(it) {
    var text = it.el.textContent;
    return it.before.indexOf(" ") < 0 ? text.replace(/ /g, " ") : text;
  }

  function count() {
    var n = 0;
    items.forEach(function (it) { if (now(it) !== it.before) n++; });
    return n;
  }

  function state(escape) {
    var message = { ontic: "edit-state", changes: count(), editable: items.length };
    if (escape) message.escape = true;
    send(message);
  }

  function enable(on) {
    editing = on;
    items.forEach(function (it) {
      var el = it.el;
      if (on) {
        el.setAttribute("contenteditable", editMode());
        el.style.outline = OUTLINE;
        el.style.outlineOffset = "2px";
      } else {
        if (it.attr === null) el.removeAttribute("contenteditable");
        else el.setAttribute("contenteditable", it.attr);
        el.style.outline = it.outline;
        el.style.outlineOffset = it.offset;
      }
    });
  }

  function bytes(text) {
    try { return new TextEncoder().encode(text).length; } catch (error) { return text.length * 3; }
  }

  function edits() {
    var changes = [], error = "";
    items.forEach(function (it) {
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

  function start() {
    if (!editing) {
      if (!items.length) items = collect();
      enable(true);
    }
    state(false);
  }

  function stop(save) {
    if (save) {
      send(edits());
      enable(false);
      return;
    }
    enable(false);
    items.forEach(function (it) {
      if (it.el.textContent !== it.before) it.el.textContent = it.before;
    });
    items = [];
  }

  window.addEventListener("message", function (event) {
    if (event.origin !== APEX || event.source !== window.parent) return;
    var message = event.data;
    if (!message || typeof message !== "object" || message.ontic !== "edit-mode") return;
    if (message.on === true) start();
    else stop(message.save === true);
  });

  // While editing, and until the saved version replaces the page: no navigation, no page
  // handlers for clicks on links, buttons or the texts being edited.
  window.addEventListener("click", function (event) {
    if (!items.length) return;
    var target = event.target;
    if (!target || !target.closest) return;
    if (target.closest(ACTIVE) || item(target)) {
      event.preventDefault();
      event.stopPropagation();
    }
  }, true);

  window.addEventListener("input", function () { if (editing) state(false); }, true);

  window.addEventListener("keydown", function (event) {
    if (!editing) return;
    if (event.key === "Escape") {
      event.preventDefault();
      state(true);
      return;
    }
    var it = item(event.target);
    if (!it) return;
    event.stopPropagation(); // typing is not the page's keyboard shortcuts
    if (event.key === "Enter" && !it.el.closest("pre")) event.preventDefault();
  }, true);

  window.addEventListener("paste", function (event) {
    if (!editing || editMode() === "plaintext-only" || !item(event.target)) return;
    event.preventDefault();
    var text = (event.clipboardData && event.clipboardData.getData("text/plain")) || "";
    document.execCommand("insertText", false, text.replace(/\s*\n\s*/g, " "));
  }, true);

  window.addEventListener("drop", function (event) { if (editing) event.preventDefault(); }, true);

  window.addEventListener("focusin", function (event) {
    var it = editing && item(event.target);
    if (it) it.el.style.outline = FOCUS;
  }, true);
  window.addEventListener("focusout", function (event) {
    var it = editing && item(event.target);
    if (it) it.el.style.outline = OUTLINE;
  }, true);
})();
