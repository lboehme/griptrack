/* Session play (#146, docs/adr/0014) client JS: work-set steppers with
 * hold-to-repeat (moved here from the old worksets.html Focus screen,
 * issue #141), the rest ring countdown (always computed from the stored
 * rest_ends_at, never a decrementing counter), and the feature-detected
 * S3 native rest bridge calls with a Screen Wake Lock fallback
 * (docs/adr/0015, #148). Vanilla, ES5-ish, no build step.
 *
 * Every /session/play action round-trips through the server and htmx swaps
 * #play-root's contents in (a fresh DOM each time), so this file never
 * caches element references across swaps -- stepper buttons are handled by
 * document-level event delegation, and the rest countdown/native hooks are
 * re-armed on every htmx:afterSettle.
 */
(function () {
  "use strict";

  function toCents(v) {
    return Math.round(v * 100);
  }

  function getLadder() {
    var el = document.getElementById("ladder-data");
    if (!el) return [];
    try {
      var ladder = JSON.parse(el.textContent);
      return ladder.filter(function (rung) {
        return rung > 0;
      });
    } catch (e) {
      return [];
    }
  }

  // Walk the loadable ladder one rung per tap; both ends clamp (see
  // CONTEXT.md: Loadable ladder).
  function stepWeight(value, dir, rungs) {
    if (!rungs.length) return value;
    if (dir > 0) {
      for (var i = 0; i < rungs.length; i++) {
        if (toCents(rungs[i]) > toCents(value)) return rungs[i];
      }
      return rungs[rungs.length - 1];
    }
    for (var j = rungs.length - 1; j >= 0; j--) {
      if (toCents(rungs[j]) < toCents(value)) return rungs[j];
    }
    return rungs[0];
  }

  function stepReps(value, dir) {
    var next = value + dir;
    return next < 1 ? 1 : next;
  }

  function renderRpeDisplay(displayEl, value) {
    if (!displayEl) return;
    var num = typeof value === "number" ? value : parseFloat(value);
    if (value === null || value === "" || value === undefined || isNaN(num)) {
      displayEl.textContent = "7";
      displayEl.classList.add("rpe-inactive");
    } else {
      displayEl.textContent = Number.isInteger(num) ? String(num) : num.toFixed(1);
      displayEl.classList.remove("rpe-inactive");
    }
  }

  function stepRpe(value, dir) {
    if (value === null) return 7.0;
    if (dir > 0) {
      if (value < 1) return 1.0;
      var up = Math.round((value + 0.5) * 10) / 10;
      return up > 10 ? 10 : up;
    }
    if (value <= 1) return null;
    if (value > 10) return 10.0;
    var down = Math.round((value - 0.5) * 10) / 10;
    return down < 1 ? 1 : down;
  }

  function doStep(btn) {
    var form = btn.closest("#set-form");
    if (!form) return;
    var field = btn.dataset.field;
    var hand = btn.dataset.hand;
    var dir = btn.classList.contains("stepper-plus") ? 1 : -1;
    var input = form.querySelector(
      '.raw-input[data-role="' + field + '-input"][data-hand="' + hand + '"]'
    );
    var display = form.querySelector(
      '[data-role="' + field + '-display"][data-hand="' + hand + '"]'
    );
    if (!input || !display) return;
    if (field === "weight") {
      var rungs = getLadder();
      var current = parseFloat(input.value) || 0;
      var next = stepWeight(current, dir, rungs);
      input.value = next;
      display.textContent = next;
    } else if (field === "reps") {
      var currentReps = parseInt(input.value, 10) || 1;
      var nextReps = stepReps(currentReps, dir);
      input.value = nextReps;
      display.textContent = nextReps;
    } else if (field === "rpe") {
      var currentRpe = input.value === "" ? null : parseFloat(input.value);
      var nextRpe = stepRpe(currentRpe, dir);
      input.value = nextRpe === null ? "" : nextRpe;
      renderRpeDisplay(display, nextRpe);
    }
  }

  function isStepperBtn(el) {
    return (
      el &&
      (el.classList.contains("stepper-btn") || el.classList.contains("stepper-btn-sm"))
    );
  }

  // ---- hold-to-repeat: 400ms initial delay, 120ms repeats, 60ms
  // accelerated after 1s held (unchanged timings from the pre-#146 Focus
  // JS, issue #141) -- delegated on document so it survives htmx swaps. ----
  var repeat = null; // { btn, timeout, interval, startTime }

  function stopRepeat() {
    if (!repeat) return;
    if (repeat.timeout) clearTimeout(repeat.timeout);
    if (repeat.interval) clearTimeout(repeat.interval);
    repeat = null;
  }

  document.addEventListener("contextmenu", function (e) {
    if (isStepperBtn(e.target.closest(".stepper-btn, .stepper-btn-sm"))) {
      e.preventDefault();
    }
  });

  document.addEventListener("pointerdown", function (e) {
    var btn = e.target.closest(".stepper-btn, .stepper-btn-sm");
    if (!btn || e.button !== 0) return;
    stopRepeat();
    doStep(btn);
    var record = { btn: btn, timeout: null, interval: null, startTime: Date.now() };
    repeat = record;
    record.timeout = setTimeout(function tick() {
      doStep(btn);
      var elapsed = Date.now() - record.startTime;
      var nextDelay = elapsed >= 1000 ? 60 : 120;
      record.interval = setTimeout(tick, nextDelay);
    }, 400);
  });

  ["pointerup", "pointercancel", "pointerleave"].forEach(function (type) {
    document.addEventListener(type, function (e) {
      var btn = e.target.closest(".stepper-btn, .stepper-btn-sm");
      if (btn) stopRepeat();
    });
  });

  // ---- set-form error surface: htmx doesn't swap non-2xx responses by
  // default, so surface the server's validation message inline instead of
  // failing silently. ----
  document.body.addEventListener("htmx:responseError", function (evt) {
    var el = document.getElementById("set-error");
    if (!el) return;
    var xhr = evt.detail && evt.detail.xhr;
    el.textContent = (xhr && xhr.responseText) || "Could not save. Please try again.";
    el.hidden = false;
  });

  // ---- rest ring: always computed from the stored rest_ends_at (never a
  // decrementing counter), so a reload or a backgrounded tab resumes at the
  // right remaining time instead of drifting (docs/adr/0014). ----
  var restTimer = null;

  function formatRestTime(totalSeconds) {
    var m = Math.floor(totalSeconds / 60);
    var s = totalSeconds % 60;
    return m + ":" + (s < 10 ? "0" : "") + s;
  }

  function stopRestTimer() {
    if (restTimer !== null) {
      clearInterval(restTimer);
      restTimer = null;
    }
  }

  function renderRest(endsAt, totalSeconds) {
    var timeEl = document.getElementById("rest-ring-time");
    var progressEl = document.getElementById("rest-ring-progress");
    var extendBtn = document.getElementById("rest-extend-btn");
    var endBtn = document.getElementById("rest-end-btn");
    if (!timeEl || !progressEl) {
      stopRestTimer();
      return;
    }
    var remaining = Math.max(0, Math.round((endsAt.getTime() - Date.now()) / 1000));
    var circumference = 2 * Math.PI * 120;
    var fraction = totalSeconds > 0 ? Math.min(1, remaining / totalSeconds) : 0;
    progressEl.style.strokeDasharray = String(circumference);
    progressEl.style.strokeDashoffset = String(circumference * (1 - fraction));
    if (remaining <= 0) {
      timeEl.textContent = "Pull";
      timeEl.classList.add("rest-pull", "rest-pull-pulse");
      if (extendBtn) extendBtn.hidden = true;
      if (endBtn && endBtn.dataset.startLabel) {
        endBtn.textContent = endBtn.dataset.startLabel;
      }
      // Deliberately *not* stopRest here: the native alarm (docs/adr/0015)
      // is the source of truth for the rest-over alert, and cancelling it as
      // the in-app ring reaches zero would race it and swallow the vibration.
      stopRestTimer();
    } else {
      timeEl.textContent = formatRestTime(remaining);
      timeEl.classList.remove("rest-pull", "rest-pull-pulse");
    }
  }

  function startRestCountdown() {
    stopRestTimer();
    var step = document.getElementById("rest-step");
    if (!step) return;
    var endsAtRaw = step.dataset.restEndsAt;
    if (!endsAtRaw) return;
    var endsAt = new Date(endsAtRaw);
    var totalSeconds = parseInt(step.dataset.totalRestSeconds, 10) || 180;
    var endBtn = document.getElementById("rest-end-btn");
    if (endBtn && !endBtn.dataset.startLabel) {
      endBtn.dataset.startLabel = "Start set " + step.dataset.nextSetNumber;
    }
    renderRest(endsAt, totalSeconds);
    restTimer = setInterval(function () {
      renderRest(endsAt, totalSeconds);
    }, 1000);

    startNativeRest(step);
  }

  // ---- S3 native rest bridge (#148, docs/adr/0015). The Android shell
  // injects window.GripTrackNative; the plain browser build has none, so
  // every call is feature-detected and wrapped (a bridge error must never
  // break the play screen). JS -> Kotlin @JavascriptInterface calls only
  // carry primitives, hence positional args rather than an object. ----
  function nativeCall(name) {
    var bridge = window.GripTrackNative;
    if (!bridge || typeof bridge[name] !== "function") return;
    var args = Array.prototype.slice.call(arguments, 1);
    try {
      bridge[name].apply(bridge, args);
    } catch (e) {}
  }

  // startRest(endsAtEpochMs, title, detail, sound, readyTitle): posts or
  // updates the lock-screen countdown and (re)schedules the rest-over
  // alarm. Re-called on every render of the rest step, so +30 s and the
  // sound toggle simply reschedule. An end already in the past is left
  // alone -- the rest is over and the alarm has (or will have) fired.
  function startNativeRest(step) {
    var endsAtMs = parseInt(step.dataset.restEndsAtMs, 10);
    if (!endsAtMs || endsAtMs <= Date.now()) return;
    nativeCall(
      "startRest",
      endsAtMs,
      step.dataset.restTitle || "",
      step.dataset.restDetail || "",
      step.dataset.restSound === "true",
      step.dataset.restReady || ""
    );
  }

  // Keep the screen on for the whole play session except the summary
  // (the session is over there), off everywhere else.
  function wantsScreenOn() {
    if (!document.getElementById("play-root")) return false;
    var stepEl = document.getElementById("play-step");
    return !(stepEl && stepEl.dataset.step === "summary");
  }

  // ---- Browser fallback: the Screen Wake Lock API, used only when there's
  // no native bridge (WebView support for it is unreliable, hence the
  // bridge). Released locks are dropped by the browser whenever the page
  // is hidden, so it's re-acquired on visibilitychange. ----
  var wakeLock = null;

  function hasBridge() {
    return !!window.GripTrackNative;
  }

  function acquireWakeLock() {
    if (hasBridge() || wakeLock || !("wakeLock" in navigator)) return;
    if (document.visibilityState !== "visible") return;
    try {
      navigator.wakeLock
        .request("screen")
        .then(function (lock) {
          wakeLock = lock;
          if (lock && lock.addEventListener) {
            lock.addEventListener("release", function () {
              if (wakeLock === lock) wakeLock = null;
            });
          }
          if (!wantsScreenOn()) releaseWakeLock();
        })
        .catch(function () {});
    } catch (e) {}
  }

  function releaseWakeLock() {
    var lock = wakeLock;
    wakeLock = null;
    if (lock) {
      try {
        var p = lock.release();
        if (p && p.catch) p.catch(function () {});
      } catch (e) {}
    }
  }

  function updateKeepScreenOn() {
    var on = wantsScreenOn();
    if (hasBridge()) {
      nativeCall("setKeepScreenOn", on);
    } else if (on) {
      acquireWakeLock();
    } else {
      releaseWakeLock();
    }
  }

  function onSettle() {
    startRestCountdown();
    // Any play step other than rest (Skip rest / Start set N / the next
    // set / the summary) means no rest is pending: cancel the notification
    // and alarm.
    if (document.getElementById("play-root") && !document.getElementById("rest-step")) {
      nativeCall("stopRest");
    }
    updateKeepScreenOn();
  }

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible" && wantsScreenOn()) acquireWakeLock();
  });

  document.addEventListener("DOMContentLoaded", onSettle);
  document.body.addEventListener("htmx:afterSettle", onSettle);

  // ---- "How did it feel?" disclosure (issue #81, restored on the play
  // work-set step in #146 review item 1): notes/deload and pain reports
  // keep autosaving per interaction -- no commit button, no edit-mode dance.
  // Delegated on document (not bound once at load) since the disclosure is
  // re-rendered fresh on every htmx swap of #play-root. ----
  function displayName(str) {
    if (!str) return "";
    var s = String(str).replace(/_/g, " ");
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  function upsertPainRow(hand, severity, note) {
    var body = document.getElementById("pain-reports-body");
    var table = document.getElementById("pain-reports-table");
    if (!body) return;
    var row = body.querySelector('tr[data-hand="' + hand + '"]');
    if (!row) {
      row = document.createElement("tr");
      row.dataset.hand = hand;
      body.appendChild(row);
    }
    row.replaceChildren();
    [displayName(hand), displayName(severity), note || ""].forEach(function (text) {
      var td = document.createElement("td");
      td.textContent = text;
      row.appendChild(td);
    });
    if (table) table.hidden = false;
  }

  document.addEventListener("change", function (e) {
    var metaForm = e.target.closest("#session-update-form");
    if (metaForm) {
      fetch(metaForm.action, {
        method: "POST",
        body: new FormData(metaForm),
        headers: { "HX-Request": "true" },
      });
      return;
    }

    var painForm = e.target.closest("#pain-report-form");
    if (painForm) {
      var severityInput = painForm.querySelector('input[name="severity"]');
      if (!severityInput || !severityInput.value) return;
      var handRadio = painForm.querySelector('input[name="hand"]:checked');
      var hand = handRadio ? handRadio.value : "left";
      var note = painForm.querySelector('input[name="note"]').value;
      var severity = severityInput.value;
      fetch(painForm.action, {
        method: "POST",
        body: new FormData(painForm),
        headers: { "HX-Request": "true" },
      }).then(function (response) {
        if (response.ok) upsertPainRow(hand, severity, note);
      });
    }
  });

  // Leaving the page (pause ✕, Back, any navigation away): screen may sleep
  // again and the rest alarm is cancelled. Reopening play on the rest step
  // re-arms it from the stored rest_ends_at.
  window.addEventListener("pagehide", function () {
    if (!document.getElementById("play-root")) return;
    nativeCall("setKeepScreenOn", false);
    nativeCall("stopRest");
    releaseWakeLock();
  });
})();
