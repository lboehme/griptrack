// Shared grip-select dimension-label updater (pinch dimension semantics —
// see CLAUDE.md). Any form with a `select.grip-select` and a sibling
// `.dimension-label` span relabels that span ("edge depth (mm)" / "block
// width (mm)") to match the selected grip's dimension_name, read off each
// <option>'s data-dimension-name attribute. Used by max_tests.html and
// Today's Change picker (#149) -- the latter arrives by htmx swap, so the
// listener is delegated and re-synced after every settle.
(function () {
  function updateLabel(select) {
    const option = select.options[select.selectedIndex];
    if (!option) return;
    const dimName = option.getAttribute("data-dimension-name");
    if (!dimName) return;
    const form = select.closest("form");
    const labelSpan = form && form.querySelector(".dimension-label");
    if (labelSpan) {
      labelSpan.textContent = dimName + " (mm)";
    }
  }

  function syncAll() {
    document.querySelectorAll("select.grip-select").forEach(updateLabel);
  }

  document.addEventListener("change", (e) => {
    if (e.target.matches && e.target.matches("select.grip-select")) updateLabel(e.target);
  });
  // setTimeout: let the DOM (and any other load-time script) settle first.
  document.addEventListener("DOMContentLoaded", () => setTimeout(syncAll, 0));
  document.addEventListener("htmx:afterSettle", syncAll);
})();
