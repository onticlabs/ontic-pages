// Edit text in place, the bar's side (served as part of bar.js, after it). The page's owner, on
// the current version, gets an Edit button. While editing, the bar shows how many texts changed,
// a short note, Save and Cancel; Escape (here or in the page) or Cancel leaves without saving,
// asking first when something changed. Save collects the changes from the page and sends them to
// the gateway, which writes a new version (edits.py); the bar's live update fades it in.
// The page's side is edit-bridge.js. To the frame: edit-mode. From it: edit-state and edits.
// Everything shown is set with textContent.
(function () {
  "use strict";
  var bar = window.onticBar;
  if (!bar) return;

  var NOTE = "Text only. Saved as a new version; older versions stay in the title menu.";
  var state = "off"; // off, editing, saving
  var changes = 0;
  var version = null; // the version being edited
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

  function changesText(n) { return n + (n === 1 ? " change" : " changes"); }

  function draw() {
    if (!ui) return;
    var on = state !== "off";
    ui.edit.hidden = on || !allowed();
    ui.tools.hidden = !on;
    ui.count.textContent = state === "saving" ? "Saving…" : "Editing: " + changesText(changes);
    ui.save.disabled = ui.cancel.disabled = state === "saving";
    document.body.classList.toggle("editing", on);
  }

  // The drop-down under Save: an error, or the question before throwing changes away.
  function show(error, confirm) {
    ui.error.textContent = error || "";
    ui.error.hidden = !error;
    ui.confirm.hidden = !confirm;
    if (confirm) ui.question.textContent = "Discard " + changesText(changes) + "?";
    ui.panel.hidden = !error && !confirm;
  }

  function start() {
    if (state !== "off" || !allowed()) return;
    state = "editing";
    changes = 0;
    version = bar.page().current;
    show("", false);
    post({ ontic: "edit-mode", on: true });
    draw();
  }

  function leave() {
    state = "off";
    changes = 0;
    show("", false);
    post({ ontic: "edit-mode", on: false });
    draw();
    // A version published while editing was held back: show it now.
    if (!bar.view.version && bar.page().current !== version) bar.swap();
  }

  function cancel() {
    if (state === "saving") return;
    if (state === "editing" && changes > 0) show("", true);
    else if (state === "editing") leave();
  }

  function save() {
    if (state !== "editing") return;
    if (!changes) return leave();
    state = "saving";
    show("", false);
    draw();
    post({ ontic: "edit-mode", on: false, save: true });
    clearTimeout(timer);
    timer = setTimeout(function () { failed("The page did not answer; try Save again."); }, 10000);
  }

  function failed(error) {
    if (state !== "saving") return;
    clearTimeout(timer);
    state = "editing";
    post({ ontic: "edit-mode", on: true }); // the edits are still in the page
    draw();
    show(error, false);
  }

  function saved(next) {
    state = "off";
    changes = 0;
    draw();
    ui.done.hidden = false;
    setTimeout(function () { ui.done.hidden = true; }, 2500);
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
      state = "editing";
      return leave();
    }
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

  bar.add({
    message: function (msg) {
      if (msg.ontic === "edit-state" && state === "editing") {
        if (typeof msg.changes === "number" && msg.changes >= 0) changes = Math.floor(msg.changes);
        draw();
        if (msg.editable === 0) show("This page has no plain text to edit.", false);
        if (msg.escape === true) cancel();
      } else if (msg.ontic === "edits") {
        send(msg);
      } else if (msg.ontic === "ready" && state !== "off") {
        // The page loaded again inside the frame: its edits are gone.
        state = "off";
        changes = 0;
        draw();
        show("The page reloaded; unsaved edits are gone.", false);
      }
    },
    render: draw,
    holds: function () { return state !== "off"; }
  });

  document.addEventListener("DOMContentLoaded", function () {
    var grow = document.querySelector(".bar .grow");
    if (!grow) return;
    ui = { pop: el("div", "pop edit-pop") };
    ui.pop.id = "edit-pop";
    ui.edit = button("edit-btn", "Edit", start);
    ui.edit.title = "Fix text on this page; Save makes a new version";
    ui.done = el("span", "edit-done", "Saved");
    ui.done.hidden = true;
    ui.tools = el("span", "edit-tools");
    ui.note = el("span", "edit-note wide", NOTE);
    ui.note.title = NOTE;
    ui.count = el("span", "edit-count");
    ui.count.setAttribute("role", "status");
    ui.cancel = button("edit-cancel", "Cancel", cancel);
    ui.save = button("edit-save", "Save", save);
    [ui.note, ui.count, ui.cancel, ui.save].forEach(function (n) { ui.tools.appendChild(n); });
    ui.panel = el("div", "panel edit-panel");
    ui.panel.setAttribute("role", "alert");
    ui.error = el("p", "error");
    ui.confirm = el("div", "edit-confirm");
    ui.question = el("p");
    ui.confirm.appendChild(ui.question);
    ui.confirm.appendChild(button("edit-keep", "Keep editing", function () { show("", false); }));
    ui.confirm.appendChild(button("edit-discard", "Discard", leave));
    ui.panel.appendChild(ui.error);
    ui.panel.appendChild(ui.confirm);
    ui.panel.addEventListener("click", function (event) { event.stopPropagation(); });
    [ui.edit, ui.done, ui.tools, ui.panel].forEach(function (n) { ui.pop.appendChild(n); });
    grow.parentNode.insertBefore(ui.pop, grow.nextSibling);
    show("", false);
    draw();

    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape" || state === "off") return;
      if (!ui.confirm.hidden) show("", false);
      else cancel();
    });
    window.addEventListener("beforeunload", function (event) {
      if (state !== "off" && changes > 0) {
        event.preventDefault();
        event.returnValue = "";
      }
    });
  });
})();
