# The rest timer gets a small native bridge: screen on, lock-screen countdown, vibrate at zero

Decided 2026-09-23, in the redesign grill that followed the UI review
(`docs/ui-review-2026-09.md`, §2.2 and Direction D2). Amends ADR-0011's
"device-gated, web-only" rest timer.

ADR-0011 made the rest timer a web countdown with the Screen Wake Lock API and
no audio. On the phone that falls short:
- The countdown only runs while the screen is on and the app is in front.
- Wake Lock support in Android WebView is unreliable.
- When rest is over, nothing tells you if you've put the phone down, and
  putting the phone down is exactly what happens between hangs.

## Decision

**Add a small, feature-detected JavaScript interface in the Android shell for
three things, and nothing more:**

1. **Keep the screen on** while a session is in progress, using the window's
   keep-screen-on flag, toggled from `/session/play`. It replaces the web wake
   lock inside the app.
2. **Lock-screen countdown.** When rest starts, post a notification using the
   system's built-in countdown clock (e.g. "Rest 1:42 · set 3 of 4 next ·
   34.5 / 35.75 kg"). The system updates the display, so no foreground service
   is needed. Tapping it opens the session.
3. **Rest-over alert.** Schedule an exact alarm for the rest end. It vibrates
   and updates the notification to "Pull, set 3", even with the screen off.
   Skipping or extending rest cancels or reschedules it.

A **sound toggle** in Settings (off by default) adds a short sound to the
rest-over alert. Vibration alone stays the default, since shared gyms are
quiet places.

Permissions:
- The notification permission, requested once, when the first rest starts.
- Vibrate.
- Exact alarms, using the timer-app permission that is granted automatically.

The web page calls the bridge only if it exists
(`window.GripTrackNative?.…`), so the browser build and the Playwright tests are
unaffected.

## Not included (deliberately)

- **Action buttons on the notification** (+30 s, Skip). They would need a
  foreground service, service-type declarations on Android 14+, and a path from
  the notification back to the server. Roughly three times the native code.
  Revisit if adjusting rest without unlocking turns out to matter.
- **Storing actual rest durations.** Still deferred, as in ADR-0011, until a
  consumer exists.

## Consequences

- The project now owns a small amount of real Kotlin beyond the WebView shell:
  a bridge class, a notification channel and an alarm receiver. The device
  smoke checklist gains rest-alarm checks: screen off, app in background, skip
  and extend.
- The web countdown remains the source of truth for what's displayed in the
  app. The native alarm is the source of truth for the alert.
