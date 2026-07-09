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

  document.addEventListener("DOMContentLoaded", function () {
    var today = localISODate();

    document.querySelectorAll("input[type=date].local-date-default").forEach(
      function (input) {
        input.value = today;
      }
    );

    document.querySelectorAll("[data-session-date]").forEach(function (el) {
      if (el.dataset.sessionDate < today) {
        el.hidden = false;
      }
    });
  });
})();
