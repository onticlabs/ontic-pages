// The command line's sign-in page: Allow posts the code (from the button) to the gateway, which
// then hands the terminal its token. Same-origin JSON, like the Share panel's writes.
(function () {
  "use strict";
  document.addEventListener("DOMContentLoaded", function () {
    var button = document.getElementById("allow");
    var result = document.getElementById("result");
    if (!button) return;
    button.addEventListener("click", function () {
      button.disabled = true;
      result.textContent = "";
      fetch("/_api/cli/approve", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: button.getAttribute("data-code") })
      }).then(function (response) {
        return response.json().then(function (body) { return { ok: response.ok, body: body }; });
      }).then(function (answer) {
        if (answer.ok) {
          button.hidden = true;
          result.textContent = "Done. Go back to your terminal; you can close this tab.";
        } else {
          result.textContent = (answer.body && answer.body.error) || "That did not work.";
        }
      }, function () {
        button.disabled = false;
        result.textContent = "Could not reach the server. Try again.";
      });
    });
  });
})();
