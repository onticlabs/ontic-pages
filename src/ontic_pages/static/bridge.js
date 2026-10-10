// The bridge between a page (this frame) and the ontic bar around it. The gateway adds one
// <script> tag for this file to a page's HTML only when it is loaded into the bar's frame;
// stored files are never changed. It tells the bar when the page is ready, where it navigated
// (path and title), that someone clicked in it, and how far it is scrolled; the bar can ask it
// to scroll back after a new version loads. A plain click on a link to the apex (another page, the
// listing) is handed to the bar, which opens it in the whole tab: the apex refuses to be framed.
// It posts to exactly one origin (the apex, written in by the gateway) and accepts messages only
// from that origin and the parent window. Its ready and nav messages carry the version this page
// was served from (data-version on the script tag, written by the gateway), so the bar knows
// what the frame shows even when a save or a publish changed the current version meanwhile.
// Every message is {ontic: "<type>", ...}; later types (comment pins, edit mode) go here too.
(function () {
  "use strict";
  var APEX = __APEX__;
  if (window.parent === window || window.parent !== window.top) return;
  var VERSION = "";
  try {
    var tag = document.currentScript;
    var served = tag && tag.getAttribute("data-version");
    if (served && /^\d{8}T\d{6}Z$/.test(served)) VERSION = served;
  } catch (error) { /* no current script: the bar falls back to the current version */ }

  function send(message) {
    try {
      window.parent.postMessage(message, APEX);
    } catch (error) { /* not inside the bar */ }
  }

  var last = "";
  function nav() {
    var path = location.pathname + location.search + location.hash;
    var title = document.title || "";
    if (path + "\n" + title === last) return;
    last = path + "\n" + title;
    send({ ontic: "nav", path: path, title: title, version: VERSION });
  }

  function ready() {
    send({ ontic: "ready", version: VERSION });
    nav();
    var title = document.querySelector("title");
    if (title && window.MutationObserver) {
      new MutationObserver(nav).observe(title, { childList: true, characterData: true, subtree: true });
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", ready);
  else ready();

  window.addEventListener("hashchange", nav);
  window.addEventListener("popstate", nav);
  ["pushState", "replaceState"].forEach(function (key) {
    var original = history[key];
    if (typeof original !== "function") return;
    history[key] = function () {
      var result = original.apply(this, arguments);
      nav();
      return result;
    };
  });

  window.addEventListener("pointerdown", function () { send({ ontic: "engaged" }); }, true);

  // Links to the apex. Only a plain left click on a link opened in this frame (or its top);
  // the page's own handlers come first (bubble phase, defaultPrevented), and a new tab or window
  // works without help.
  window.addEventListener("click", function (event) {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey
        || event.shiftKey || event.altKey) return;
    var link = event.target && event.target.closest ? event.target.closest("a[href]") : null;
    if (!link || link.hasAttribute("download")) return;
    var target = (link.getAttribute("target") || "").toLowerCase();
    if (target && target !== "_self" && target !== "_top" && target !== "_parent") return;
    var url;
    try { url = new URL(link.href, location.href); } catch (error) { return; }
    if (url.origin !== APEX) return;
    event.preventDefault();
    send({ ontic: "open", url: url.href });
  });

  var timer = 0;
  window.addEventListener("scroll", function () {
    if (timer) return;
    timer = setTimeout(function () {
      timer = 0;
      send({ ontic: "scroll", y: Math.max(0, Math.round(window.scrollY)) });
    }, 150);
  }, { passive: true });

  window.addEventListener("message", function (event) {
    if (event.origin !== APEX || event.source !== window.parent) return;
    var message = event.data;
    if (!message || typeof message !== "object") return;
    if (message.ontic === "scroll-to" && typeof message.y === "number" && isFinite(message.y)
        && message.y >= 0) {
      var y = message.y;
      window.scrollTo(0, y);
      // A frame that was never painted cannot scroll yet; and while still loading the page may
      // not be that tall: so again after the next paint, and once it has loaded.
      if (window.requestAnimationFrame) {
        requestAnimationFrame(function () { window.scrollTo(0, y); });
      }
      if (document.readyState !== "complete") {
        window.addEventListener("load", function () { window.scrollTo(0, y); }, { once: true });
      }
    }
  });
})();
