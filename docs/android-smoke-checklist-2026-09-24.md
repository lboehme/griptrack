# GripTrack Android On-Device Smoke Checklist: Native Rest Bridge (#148 / docs/adr/0015)

**Test Date**: 2026-09-24  
**Target Hardware**: Samsung Galaxy S22 Ultra (SM-S908B), Android 16 (arm64-v8a)  
**App Build**: `app-debug.apk` (`targetSdk = 35`, `minSdk = 26`, Chaquopy 17.0.0, CPython 3.13, FastAPI + SQLite)  
**Scope**: the S3 native rest bridge (`window.GripTrackNative`): keep the screen on during `/session/play`, the lock-screen rest countdown notification, the exact rest-over alarm (vibration, optional sound), and rescheduling or cancelling it from Skip rest, +30 s and pause.

> The Kotlin in this slice (`RestBridge.kt`, `RestAlarmReceiver.kt`, the `MainActivity.kt` wiring, and the manifest changes) was written in a container without an Android SDK. **It has never been compiled.** Step 1 is the first compile.

---

## 1. Prerequisites & Build Verification

- [ ] **Gradle Build**: `./gradlew assembleDebug` builds `app-debug.apk` with zero errors. First compile of `RestBridge.kt` / `RestAlarmReceiver.kt`.
- [ ] **Unit Tests**: `./gradlew testDebugUnitTest` passes, including the new `RestBridgeValidationTest` (rest-end window, text caps).
- [x] **Lint**: `scripts/lint` clean.
- [x] **Backend Tests**: `scripts/test` and `scripts/test-browser` pass (the stubbed-bridge Playwright specs in `tests/e2e/test_session_play_native_bridge.py`).
- [ ] **APK Installation**: `adb install -r app/build/outputs/apk/debug/app-debug.apk` installs over the previous build (the migration adds `users.rest_sound` on first launch).
- [ ] **Permissions Declared**: `adb shell dumpsys package org.griptrack.app | grep -A30 "requested permissions"` lists `POST_NOTIFICATIONS`, `VIBRATE`, `USE_EXACT_ALARM`.

Logs for the whole checklist: `adb logcat -s GripTrackRest GripTrackActivity GripTrackServer`.

---

## 2. Keep Screen On

Set the phone's screen timeout short first (Settings → Display → Screen timeout → 15 s) so each check takes seconds.

| # | Step | Expected Result | Device Verification | Status |
|---|------|-----------------|---------------------|--------|
| 1 | **Screen stays on in play** | Start a session and stay on `/session/play` (warmup rung, work set, rest) without touching the phone for longer than the timeout. | The screen never dims or sleeps on any play step. | **PENDING DEVICE** |
| 2 | **Screen sleeps elsewhere** | Tap ✕ (pause) to go Home, or open Trends / Climbs / Profile, and wait past the timeout. | The screen dims and sleeps normally. | **PENDING DEVICE** |
| 3 | **Screen sleeps on the summary** | Finish the last set so the "All sets done" summary shows, then wait past the timeout. | The screen sleeps normally on the summary. | **PENDING DEVICE** |

---

## 3. First Rest: Notification Permission

| # | Step | Expected Result | Device Verification | Status |
|---|------|-----------------|---------------------|--------|
| 4 | **Asked once, at the first rest** | On a fresh install (or after clearing app data), commit the first non-final set so the rest step shows. | Android's "Allow GripTrack to send you notifications?" dialog appears once. It does not appear at app launch, and it does not appear again on later rests whatever you answered. | **PENDING DEVICE** |
| 5 | **"Rest timer" channel** | Settings → Apps → GripTrack → Notifications. | A single "Rest timer" category exists. | **PENDING DEVICE** |

---

## 4. Lock-Screen Countdown & Rest-Over Alert

| # | Step | Expected Result | Device Verification | Status |
|---|------|-----------------|---------------------|--------|
| 6 | **Countdown notification** | Allow notifications. Commit a non-final set and pull down the shade. | One GripTrack notification: title "Rest · set N of M next", text with the next set's loads (e.g. "34.5 / 35.75 kg"), and a system clock counting down to 0:00 that matches the in-app ring within a second or two. It makes no sound or vibration when it appears. | **PENDING DEVICE** |
| 7 | **Lock screen shows the countdown** | During a rest, press the power button, then wake to the lock screen without unlocking. | The countdown notification is visible on the lock screen and still counting down. | **PENDING DEVICE** |
| 8 | **Vibrates at 0:00 with the screen off** | Start a rest, turn the screen off, put the phone down and wait. | At 0:00 the phone vibrates a short pattern (roughly buzz, buzz, long buzz) with the screen off. The notification changes to "Pull. Set N is ready". | **PENDING DEVICE** |
| 9 | **Vibrates with the app in the background** | Start a rest, press Home (the app stays alive in the background), and wait. | It vibrates at 0:00 and the notification changes to "Pull. Set N is ready". | **PENDING DEVICE** |
| 10 | **In-app 0:00 doesn't swallow the alert** | Start a rest and watch the ring in the app, screen on, until it reads "Pull". | It still vibrates at 0:00. The in-app ring reaching zero must not cancel the alarm. | **PENDING DEVICE** |
| 11 | **Tap reopens play on the right step** | After step 8 or 9, tap the notification (unlock if prompted). | GripTrack opens on `/session/play` on the rest step ("Pull" / "Start set N"), not on Home. Repeat after `adb shell am kill org.griptrack.app` during a rest: the alarm still fires, and tapping the notification cold-starts the app back onto the play step (the #140 restore, within 3 h). | **PENDING DEVICE** |

---

## 5. Skip, +30 s, Pause

| # | Step | Expected Result | Device Verification | Status |
|---|------|-----------------|---------------------|--------|
| 12 | **Skip rest cancels** | Start a rest, tap "Skip rest", turn the screen off and wait past the original end. | The notification disappears immediately. No vibration at the old end time. | **PENDING DEVICE** |
| 13 | **+30 s reschedules** | Start a rest, tap "+30 s" once, turn the screen off. | The notification countdown jumps by 30 s. The vibration comes 30 s later than the original end, not at it, and only once. | **PENDING DEVICE** |
| 14 | **Start set N clears the "Pull" notification** | Let a rest run out (vibration + "Pull. Set N is ready"), then tap "Start set N" in the app. | The "Pull" notification is removed. | **PENDING DEVICE** |
| 15 | **Pause (✕) cancels** | Start a rest, tap ✕ in the top bar, turn the screen off and wait past the end. | The notification disappears. No vibration. Reopening the session from Home re-arms the countdown and alarm if rest time remains. | **PENDING DEVICE** |
| 16 | **Back cancels** | Start a rest and press the system Back button to leave play. | Same as the pause check: the notification disappears and there's no vibration. | **PENDING DEVICE** |

---

## 6. Notifications Denied

| # | Step | Expected Result | Device Verification | Status |
|---|------|-----------------|---------------------|--------|
| 17 | **Still vibrates without notifications** | Settings → Apps → GripTrack → Notifications → off (or deny the permission dialog on a fresh install). Start a rest, turn the screen off, wait. | No notification anywhere, but the phone still vibrates at 0:00. The app doesn't crash or show an error. | **PENDING DEVICE** |

---

## 7. Rest Sound Toggle

| # | Step | Expected Result | Device Verification | Status |
|---|------|-----------------|---------------------|--------|
| 18 | **Off by default: vibration only** | Ringer on (not silent or vibrate). Let a rest run out with the toggle showing "Sound at 0:00: off". | Vibration only, no sound. | **PENDING DEVICE** |
| 19 | **On: vibration plus sound** | On the rest step, tap "Sound at 0:00: off" so it reads "on", and let the rest run out. | Vibration plus the default notification sound, once. The countdown itself stays silent when it's posted. | **PENDING DEVICE** |
| 20 | **Persists** | Force-stop and relaunch the app, then start another rest. | The toggle still reads "on". Turn it off again, let a rest run out: vibration only. | **PENDING DEVICE** |
| 21 | **Ringer on silent / vibrate with the sound on** | Toggle on, phone ringer on vibrate. | Vibration, no sound. The sound uses notification-event audio, so it follows the ringer mode. | **PENDING DEVICE** |

---

## 8. Architecture & Implementation Notes

1. **Bridge** (`RestBridge.kt`): registered with `webView.addJavascriptInterface(restBridge, "GripTrackNative")`. Its methods are `setKeepScreenOn(on)`, `startRest(endsAtEpochMs, title, detail, sound, readyTitle)` and `stopRest()`. Calls are ignored unless the loaded page is the loopback server (`MainActivity.onPageStarted` sets `pageIsTrusted`). The bridge rejects a rest end in the past or more than 30 minutes ahead, and it caps text at 80 characters and strips control characters.
2. **Notification**: the "Rest timer" channel (`IMPORTANCE_DEFAULT`, silent, public on the lock screen) posts notification id 148. The countdown uses `setUsesChronometer(true)`, `setChronometerCountDown(true)` and `setWhen(endsAt)`. There is no foreground service and there are no action buttons. Tapping it works like the launcher icon.
3. **Alarm**: `setExactAndAllowWhileIdle(RTC_WAKEUP, endsAt)` when `canScheduleExactAlarms()` (always true below API 31; `USE_EXACT_ALARM` is granted at install on 33+). Otherwise it falls back to `setAndAllowWhileIdle`. The same `PendingIntent` (request code 148, `FLAG_IMMUTABLE`) is replaced on +30 s and cancelled by `stopRest`.
4. **Receiver** (`RestAlarmReceiver.kt`, `exported=false`): vibrates directly with `USAGE_ALARM` attributes, so it still vibrates in the background and without notification permission. It plays the default notification sound when `sound` is true, then replaces the notification with the "Pull" line.
5. **Web side** (`backend/static/steppers.js`): every bridge call is feature-detected. `startRest` runs on each render of the rest step, using the server's `data-rest-ends-at-ms`. `stopRest` runs on any other play step and on `pagehide`. `setKeepScreenOn` is true on play steps and false on the summary and on `pagehide`. With no bridge, the page uses the Screen Wake Lock API instead.
