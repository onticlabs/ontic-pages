// The bridge between a page (this frame) and the ontic bar around it. The gateway adds one
// <script> tag for this file to a page's HTML only when it is loaded into the bar's frame;
// stored files are never changed. It tells the bar when the page is ready, where it navigated
// (path and title), that someone clicked in it, and how far it is scrolled; the bar can ask it
// to scroll back after a new version loads. It posts to exactly one origin (the apex, written
// in by the gateway) and accepts messages only from that origin and the parent window.
// Every message is {ontic: "<type>", ...}; later types (comment pins, edit mode) go here too.
(function () {
  "use strict";
  var APEX = __APEX__;
  if (window.parent === window || window.parent !== window.top) return;

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
    send({ ontic: "nav", path: path, title: title });
  }

  function ready() {
    send({ ontic: "ready" });
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
