// Edit text in place, the bar's side (served as part of bar.js, after it). For the page's owner
// on the current version, editing is always on: each time a page loads in the frame the bar
// tells it so (edit-mode), and the page makes its texts editable (edit-bridge.js). The bar shows
// nothing about it until a text changed; then "N changes", Save and Discard (Discard asks here
// first). Cmd/Ctrl+S, here or in the page, saves. Save collects the changes from the page and
// sends them to the gateway, which writes a new version (edits.py); the bar's live update fades
// it in. While there are unsaved changes a newly published version waits, and leaving the tab
// asks first. Comment mode suspends editing in the page itself (it hears comment-mode too).
// To the frame: edit-mode. From it: edit-state and edits. Everything shown is set with
// textContent.
(function () {
  "use strict";
  var bar = window.onticBar;
  if (!bar) return;

  var NOTE = "Text only. Saved as a new version; older versions stay in the title menu.";
  var state = "idle"; // idle, confirm (asking before Discard), saving (asked the page), posting
  var changes = 0;
  var version = null; // the version the page in the frame shows
  var timer = 0;
  var ui = null;

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text) node.textContent = text;
    return node;
  }
  function button(cls, text, action) {
    var node = el("button", cls, text);
    node.type = "button";
    node.addEventListener("click", function (event) {
      event.stopPropagation();
      action();
    });
    return node;
  }

  function post(message) {
    var f = bar.frame();
    try {
      f.contentWindow.postMessage(message, bar.origin);
    } catch (error) { /* the frame is gone */ }
  }

  function allowed() {
    var page = bar.page();
    return page.role === "owner" && (!bar.view.version || bar.view.version === page.current);
  }

  function busy() { return state === "saving" || state === "posting"; }
  function unsaved() { return changes > 0 || busy(); }
  function changesText(n) { return n + (n === 1 ? " change" : " changes"); }

  function draw() {
    if (!ui) return;
    ui.tools.hidden = !unsaved();
    ui.count.textContent = busy() ? "Saving…" : changesText(changes);
    ui.save.disabled = ui.discard.disabled = busy();
    ui.pop.hidden = ui.tools.hidden && ui.panel.hidden && ui.done.hidden;
    document.body.classList.toggle("editing", unsaved());
  }

  // The drop-down under the counter: an error, or the question before throwing changes away.
  function show(error, confirm) {
    if (!ui) return;
    ui.error.textContent = error || "";
    ui.error.hidden = !error;
    ui.confirm.hidden = !confirm;
    if (confirm) ui.question.textContent = "Discard " + changesText(changes) + "?";
    ui.panel.hidden = !error && !confirm;
    draw();
  }

  // A page loaded in the frame: editing starts there, with nothing changed yet.
  function start() {
    var lost = changes > 0 && !busy();
    clearTimeout(timer);
    state = "idle";
    changes = 0;
    version = bar.page().current;
    if (allowed()) post({ ontic: "edit-mode", on: true });
    show(lost ? "The page reloaded; unsaved changes are gone." : "", false);
  }

  // Back to no changes: show a version published meanwhile.
  function settled() {
    if (!bar.view.version && bar.page().current !== version) bar.swap();
  }

  function discard() {
    if (state === "idle" && changes > 0) {
      state = "confirm";
      show("", true);
    }
  }

  function keep() {
    if (state !== "confirm") return;
    state = "idle";
    show("", false);
  }

  function discarded() {
    if (state !== "confirm") return;
    state = "idle";
    changes = 0;
    post({ ontic: "edit-mode", on: true, discard: true });
    show("", false);
    settled();
  }

  function save() {
    if (!changes || busy()) return;
    state = "saving";
    show("", false);
    post({ ontic: "edit-mode", on: false, save: true });
    clearTimeout(timer);
    timer = setTimeout(function () { failed("The page did not answer; try Save again."); }, 10000);
  }

  function failed(error) {
    if (!busy()) return;
    clearTimeout(timer);
    state = "idle";
    post({ ontic: "edit-mode", on: true }); // the edits are still in the page
    show(error, false);
  }

  function saved(next) {
    state = "idle";
    changes = 0;
    show("", false);
    ui.done.hidden = false;
    draw();
    setTimeout(function () { ui.done.hidden = true; draw(); }, 2500);
    bar.update(next); // the new current version fades in
  }

  function send(message) {
    if (state !== "saving") return;
    clearTimeout(timer);
    if (typeof message.error === "string" && message.error) return failed(message.error.slice(0, 300));
    if (typeof message.path !== "string" || !Array.isArray(message.changes)) {
      return failed("Could not read the changes from the page.");
    }
    if (!message.changes.length) {
      state = "idle";
      changes = 0;
      post({ ontic: "edit-mode", on: true });
      show("", false);
      return settled();
    }
    state = "posting"; // another answer from the page is not sent again
    var name = bar.page().name;
    fetch("/_api/pages/" + encodeURIComponent(name) + "/edits", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ version: version, path: message.path, changes: message.changes })
    }).then(function (response) {
      return response.json().then(function (body) { return { ok: response.ok, body: body }; });
    }).then(function (result) {
      if (result.ok && result.body && result.body.page) saved(result.body.page);
      else failed((result.body && result.body.error) || "Could not save.");
    }, function () {
      failed("Could not reach the server; try Save again.");
    });
  }

  // The page's count. A message about an earlier save stays until the count moves.
  function changed(n) {
    if (typeof n !== "number" || !(n >= 0) || n > 1e6) return;
    n = Math.floor(n);
    var moved = n !== changes;
    changes = n;
    if (!changes && state === "confirm") state = "idle";
    if (state === "confirm") show("", true);
    else if (moved) show("", false);
    else draw();
    if (moved && !changes) settled(); // every change undone by hand
  }

  function saveKey(event) {
    var key = String(event.key || "").toLowerCase();
    return key === "s" && (event.metaKey || event.ctrlKey) && !event.altKey;
  }

  bar.add({
    message: function (msg) {
      if (msg.ontic === "ready") {
        start();
      } else if (msg.ontic === "edit-state" && allowed() && !busy()) {
        changed(msg.changes);
        if (msg.save === true) save();
      } else if (msg.ontic === "edits") {
        send(msg);
      }
    },
    render: draw,
    holds: unsaved
  });

  document.addEventListener("DOMContentLoaded", function () {
    var grow = document.querySelector(".bar .grow");
    if (!grow) return;
    ui = { pop: el("div", "pop edit-pop") };
    ui.pop.id = "edit-pop";
    ui.done = el("span", "edit-done", "Saved");
    ui.done.hidden = true;
    ui.tools = el("span", "edit-tools");
    ui.tools.title = NOTE;
    ui.count = el("span", "edit-count");
    ui.count.setAttribute("role", "status");
    ui.save = button("edit-save", "Save", save);
    ui.save.title = NOTE + " (⌘S or Ctrl+S)";
    ui.discard = button("edit-discard", "Discard", discard);
    ui.discard.title = "Put the original text back";
    [ui.count, ui.save, ui.discard].forEach(function (n) { ui.tools.appendChild(n); });
    ui.panel = el("div", "panel edit-panel");
    ui.panel.setAttribute("role", "alert");
    ui.error = el("p", "error");
    ui.confirm = el("div", "edit-confirm");
    ui.question = el("p");
    ui.confirm.appendChild(ui.question);
    ui.confirm.appendChild(button("edit-keep", "Keep editing", keep));
    ui.confirm.appendChild(button("edit-really", "Discard", discarded));
    ui.panel.appendChild(ui.error);
    ui.panel.appendChild(ui.confirm);
    ui.panel.addEventListener("click", function (event) { event.stopPropagation(); });
    [ui.done, ui.tools, ui.panel].forEach(function (n) { ui.pop.appendChild(n); });
    grow.parentNode.insertBefore(ui.pop, grow.nextSibling);
    show("", false);

    document.addEventListener("keydown", function (event) {
      if (saveKey(event) && changes > 0) {
        event.preventDefault();
        save();
      } else if (event.key === "Escape") {
        if (state === "confirm") keep();
        else if (!ui.error.hidden) show("", false);
      }
    });
    window.addEventListener("beforeunload", function (event) {
      if (unsaved()) {
        event.preventDefault();
        event.returnValue = "";
      }
    });
  });
})();
