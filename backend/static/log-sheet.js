/* The ＋ Log sheet and Today's Change picker (#149): the few bits htmx
 * can't do on its own. Opening either is an htmx swap with no hx-push-url,
 * so Android Back never has to step through them; closing is local (empty
 * the slot) rather than a navigation. Without JS, the close controls are
 * plain links back to Today. Vanilla, ES5-ish, no build step. */
(function () {
  "use strict";

  function sheetSlot() {
    return document.getElementById("log-sheet-slot");
  }

  function closeSheet() {
    var slot = sheetSlot();
    if (slot) slot.replaceChildren();
  }

  document.addEventListener("click", function (e) {
    var sheetClose = e.target.closest("[data-sheet-close]");
    if (sheetClose && sheetSlot()) {
      e.preventDefault();
      closeSheet();
      return;
    }
    var pickerClose = e.target.closest("[data-picker-close]");
    if (pickerClose) {
      var picker = pickerClose.closest("#today-picker");
      if (picker) {
        e.preventDefault();
        picker.remove();
      }
    }
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && document.querySelector(".log-sheet")) closeSheet();
  });

  // "Log 7A flash": the climb button names what it's about to save.
  function syncClimbLabel(form) {
    var btn = form.querySelector(".sheet-submit");
    if (!btn) return;
    var grade = form.querySelector('input[name="grade"]:checked');
    var style = form.querySelector('input[name="style"]:checked');
    if (!grade) {
      btn.textContent = btn.dataset.label || "Log climb";
      return;
    }
    var gradeText = grade.value;
    if (gradeText === "__other__") {
      var other = form.querySelector('input[name="grade_other"]');
      gradeText = other && other.value.trim() ? other.value.trim() : "climb";
    }
    var styleText = style ? style.nextElementSibling.textContent.trim().toLowerCase() : "";
    btn.textContent = ("Log " + gradeText + " " + styleText).trim();
  }

  document.addEventListener("change", function (e) {
    var form = e.target.closest(".sheet-climb");
    if (form) syncClimbLabel(form);
  });
  document.addEventListener("input", function (e) {
    var form = e.target.closest(".sheet-climb");
    if (form && e.target.name === "grade_other") syncClimbLabel(form);
  });

  // htmx doesn't swap 4xx responses, so surface the server's validation
  // message inside the sheet instead of failing silently.
  document.addEventListener("htmx:responseError", function (evt) {
    var el = document.getElementById("sheet-error");
    if (!el) return;
    var xhr = evt.detail && evt.detail.xhr;
    el.textContent = (xhr && xhr.responseText) || "Could not save. Please try again.";
    el.hidden = false;
  });

  // Move focus into a freshly opened sheet so keyboard / TalkBack users
  // land on it.
  document.addEventListener("htmx:afterSettle", function (evt) {
    var target = evt.detail && evt.detail.target;
    if (!target || target.id !== "log-sheet-slot") return;
    var tab = target.querySelector(".sheet-tab.active");
    if (tab) tab.focus({ preventScroll: true });
  });
})();
