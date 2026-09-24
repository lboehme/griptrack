// Shared client-local-date helpers (see CLAUDE.md: multi-session days).
//
// The server can only default date inputs from its own clock, which is
// wrong for a user logging late at night in a different timezone. This
// small snippet is the one place that corrects that: on load, it (1) sets
// every "default to today" date input to the browser's local date, and
// (2) unhides the past-session warning banner on session pages whose date
// is before the browser's local date. No timezone is ever stored — this
// is a same-page, load-time comparison only.
(function () {
  function pad(n) {
    return String(n).padStart(2, "0");
  }

  function localISODate() {
    var d = new Date();
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
  }

  window.GripTrackClientDate = { localISODate: localISODate };

  function apply(root) {
    var today = localISODate();

    // Visible date inputs and hidden ones (Today's Start form, the ＋ Log
    // sheet) alike -- but only while still pristine: once filled (or edited
    // by the user) an input is marked, so a later unrelated htmx swap never
    // resets a date the user picked (PR #154 review).
    root.querySelectorAll("input.local-date-default").forEach(function (input) {
      if (input.dataset.localDateSet) return;
      input.value = today;
      input.dataset.localDateSet = "1";
    });

    root.querySelectorAll("[data-session-date]").forEach(function (el) {
      if (el.dataset.sessionDate < today) {
        el.hidden = false;
      }
    });
  }

  document.addEventListener("input", function (e) {
    var input = e.target;
    if (input.classList && input.classList.contains("local-date-default")) {
      input.dataset.localDateSet = "1";
    }
  });

  document.addEventListener("DOMContentLoaded", function () {
    apply(document);
  });
  // htmx-swapped fragments (the ＋ Log sheet, Today re-rendering in place,
  // #149) need the same correction as a fresh page load.
  document.addEventListener("htmx:afterSettle", function () {
    apply(document);
  });
})();
