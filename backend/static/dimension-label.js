// Shared grip-select dimension-label updater (pinch dimension semantics —
// see CLAUDE.md). Any form with a `select.grip-select` and a sibling
// `.dimension-label` span relabels that span ("edge depth (mm)" / "block
// width (mm)") to match the selected grip's dimension_name, read off each
// <option>'s data-dimension-name attribute. Deduplicated out of
// max_tests.html and new_session.html, which both shipped this verbatim.
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("select.grip-select").forEach((select) => {
    const updateLabel = () => {
      const option = select.options[select.selectedIndex];
      if (!option) return;
      const dimName = option.getAttribute("data-dimension-name");
      if (!dimName) return;
      const form = select.closest("form");
      const labelSpan = form.querySelector(".dimension-label");
      if (labelSpan) {
        labelSpan.textContent = dimName + " (mm)";
      }
    };
    select.addEventListener("change", updateLabel);
    // Use setTimeout to ensure the DOM (and any other load-time script) is
    // fully settled before the initial label sync.
    setTimeout(updateLabel, 0);
  });
});
