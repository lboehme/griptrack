# GripTrack Android On-Device Smoke Checklist (#139, #140 / docs/ui-review-2026-09.md §2.1, §2.3, §2.4, §2.5, §2.7)

**Test Date**: 2026-09-23  
**Target Hardware**: Samsung Galaxy S22 Ultra (SM-S908B), Android 16 (arm64-v8a)  
**App Build**: `app-debug.apk` (`targetSdk = 35`, Chaquopy 17.0.0, CPython 3.13, FastAPI + SQLite)  
**Scope**: Android shell edge-to-edge handling, keyboard (IME) insets, single splash screen (`core-splashscreen`), themed status/navigation bars, mid-session lifecycle preservation across recreation & process death (§2.3), and app-like Back navigation (§2.4).

---

## 1. Prerequisites & Build Verification

- [x] **Gradle Build**: `./gradlew assembleDebug` builds `app-debug.apk` cleanly with zero errors and zero warnings.
- [x] **Unit Tests**: `./gradlew testDebugUnitTest` passed all Android navigation & lifecycle unit tests.
- [x] **Lint**: `scripts/lint` clean (Ruff, Mypy 26 source files, Pip-audit 0 vulnerabilities).
- [x] **Backend Tests**: `scripts/test` passed 402/402 tests.
- [ ] **APK Installation**: `adb install -r app/build/outputs/apk/debug/app-debug.apk` streams and installs successfully.

---

## 2. Single Launch Screen Verification (§2.5)

| # | Step | Expected Result | Device Verification | Status |
|---|------|-----------------|---------------------|--------|
| 1 | **Cold Launch Appearance** | System splash screen appears instantly with dark ground (`@color/splash_bg` `#18181B`) and GripTrack adaptive launcher icon. | Cold start shows system splash without flicker. | **PENDING DEVICE** |
| 2 | **Single Splash Flow (Happy Path)** | System splash remains on screen (`setKeepOnScreenCondition { ServerManager.state != RUNNING }`) until the embedded Python server is ready and healthy. The old secondary spinner container ("Starting GripTrack…") is dropped; the splash smoothly transitions directly into the loaded WebView. | Single branded launch screen; zero dual-splash or intermediate loading text on successful boot. | **PENDING DEVICE** |
| 3 | **Error / Recovery State** | If the embedded server fails to start (e.g. simulated port collision or corrupted DB), the splash condition releases, revealing `errorContainer` with error title, monospace stack trace, and working "Retry" button. | When error is injected, splash dismisses to show `errorContainer` and allows user retry. | **PENDING DEVICE** |

---

## 3. Edge-to-Edge System Bar Insets (§2.1)

| # | Step | Expected Result | Device Verification | Status |
|---|------|-----------------|---------------------|--------|
| 4 | **Edge-to-Edge Window Setup** | `WindowCompat.setDecorFitsSystemWindows(window, false)` is active on Android 15+. Content renders edge-to-edge behind transparent system bars. | Full display utilized edge-to-edge without black letterbox bars. | **PENDING DEVICE** |
| 5 | **Status Bar Insets (Top)** | WebView content is padded natively via `WindowInsetsCompat.Type.systemBars()`. The sticky header (`.app-header` with "GripTrack." and "Log out") sits comfortably below the system clock, battery, and camera punch hole. | Header text and actions are never clipped or overlapped by the status bar or camera cutout. | **PENDING DEVICE** |
| 6 | **Gesture / Navigation Bar Insets (Bottom)** | Bottom tab bar (`.tabbar`: Home, Session, Trends, Climbs, Profile) sits safely above the Android gesture navigation pill or 3-button navigation bar. | Tab bar items are fully reachable and not obscured by the gesture navigation bar. | **PENDING DEVICE** |
| 7 | **No Double Inset Offset** | Native padding on `webView` ensures WebView bounds stay within the safe viewport. Internal CSS `env(safe-area-inset-top)` and `env(safe-area-inset-bottom)` resolve to `0px` in WebView, preventing double spacing. | Header and tab bar margins match web design without extra unintended gap. | **PENDING DEVICE** |

---

## 4. Keyboard (IME) Inset Verification (§2.1)

| # | Step | Expected Result | Device Verification | Status |
|---|------|-----------------|---------------------|--------|
| 8 | **Form Input Focus (Climbs / Profile / Max Tests)** | Tap an input or select at the bottom of the screen (e.g. Profile weight, Climbs notes, Max test load). | Keyboard opens (`WindowInsetsCompat.Type.ime()`); WebView bottom padding expands to keyboard height, pushing input and action buttons into view. | **PENDING DEVICE** |
| 9 | **Keyboard Dismissal** | Dismiss keyboard with Back gesture or by tapping outside input. | Bottom padding smoothly returns to system navigation bar height without layout distortion or lingering gap. | **PENDING DEVICE** |

---

## 5. Themed Status & Navigation Bars (§2.7)

| # | Step | Expected Result | Device Verification | Status |
|---|------|-----------------|---------------------|--------|
| 10 | **Removal of Hardcoded Orange Status Bar** | Orange status bar (`#E8532C`) is removed from `themes.xml`. System bars are transparent (`@android:color/transparent`), drawing the app background. | Status and navigation bars render seamless background instead of solid orange block. | **PENDING DEVICE** |
| 11 | **Light Mode Contrast** | System set to Light mode: `WindowInsetsControllerCompat` sets `isAppearanceLightStatusBars = true` and `isAppearanceLightNavigationBars = true`. | Status bar icons (time, battery, Wi-Fi) and navigation bar buttons/pill render with dark contrast for readability. | **PENDING DEVICE** |
| 12 | **Dark Mode Contrast** | System set to Dark mode: `WindowInsetsControllerCompat` sets `isAppearanceLightStatusBars = false` and `isAppearanceLightNavigationBars = false`. | Status bar icons and navigation bar buttons/pill render with light/white contrast against the dark background. | **PENDING DEVICE** |
| 13 | **System Theme Switch (Resume / Recreate)** | Toggle system dark/light theme while app is backgrounded or in split screen. | On resume, `updateSystemBarAppearance()` refreshes icon contrast immediately to match current `Configuration.uiMode`. | **PENDING DEVICE** |

---

## 6. Mid-Session Lifecycle & State Restoration (§2.3)

| # | Step | Expected Result | Device Verification | Status |
|---|------|-----------------|---------------------|--------|
| 14 | **Mid-Session Dark Mode Toggle** | While on `/session/warmup` or `/session/worksets` with active timer or unsaved stepper input, toggle system dark mode (via Quick Settings tile or schedule). | Activity is NOT recreated (`uiMode` in `configChanges`). WebView updates colors via CSS `prefers-color-scheme` live; active rest countdown and uncommitted stepper values are completely preserved. | **PENDING DEVICE** |
| 15 | **Process Kill & Relaunch (< 3 Hours)** | While on `/session/worksets` (e.g. set 2 of 3), switch to memory-heavy app (camera/maps) or force-stop process (`adb shell am kill org.griptrack.app`). Relaunch within 3 hours. | App boots through single splash and restores directly into the active `/session/worksets` URL from saved state instead of dumping user on `/`. | **PENDING DEVICE** |
| 16 | **Process Kill & Relaunch (> 3 Hours)** | Kill app process while on a session page. Relaunch after more than 3 hours (or simulated timestamp expiry). | Because 3 hours have elapsed, session restoration window has expired; app cleanly opens to Home (`/`). | **PENDING DEVICE** |
| 17 | **Non-Session Page Resurrection** | Kill process while on `/dashboard`, `/climbs`, `/profile`, or `/session/new`. Relaunch app. | Saved URL is not an active `/session/...` workout page; app launches directly to Home (`/`). | **PENDING DEVICE** |

---

## 7. App Navigation & Back Button Behaviour (§2.4)

| # | Step | Expected Result | Device Verification | Status |
|---|------|-----------------|---------------------|--------|
| 18 | **Tab Roots to Home** | Navigate to any tab root (`/dashboard`, `/climbs`, `/profile`, `/session/new`). Press Back button or trigger Back gesture. | App navigates to Home (`/`) and clears forward/backward history rather than stepping back through every visited tab. | **PENDING DEVICE** |
| 19 | **Home Exit** | From Home (`/`), press Back button or trigger Back gesture. | App finishes activity and exits cleanly to Android launcher/home screen (`finish()`). | **PENDING DEVICE** |
| 20 | **Mid-Flow Back Navigation** | From `/session/new`, start warmup (`/session/warmup`), then proceed to worksets (`/session/worksets`). Press Back. | Back steps back inside the flow to `/session/warmup`. Pressing Back again from warmup steps back to `/session/new`. | **PENDING DEVICE** |
| 21 | **Never Return to Auth After Sign-In** | Start from `/login` or `/register`, enter credentials, and log in to `/`. Press Back. | Back stack history is cleared upon navigation away from auth pages; pressing Back exits app instead of stranding user on `/login` or `/register`. | **PENDING DEVICE** |

---

## 8. Architecture & Implementation Notes

1. **`androidx.core:core-splashscreen:1.0.1`**: Installed and wired in `MainActivity.onCreate()` before `super.onCreate()`. Starting theme `Theme.GripTrack.Starting` switches to `Theme.GripTrack` after splash.
2. **Native Inset Handling**: `ViewCompat.setOnApplyWindowInsetsListener` handles combined `systemBars() or ime()` insets on `webView` and `errorContainer`.
3. **Configuration Changes**: `uiMode` is added to `android:configChanges` in `AndroidManifest.xml` alongside `orientation|screenSize|keyboardHidden|screenLayout`. Dark mode changes are handled live by WebView via CSS `prefers-color-scheme` without Activity recreation.
4. **Session State Restoration**: `onPageFinished` stores same-origin path + query and `System.currentTimeMillis()` in `SharedPreferences` and `onSaveInstanceState`. On startup, `onServerReady` restores `/session/...` pages saved within a 3-hour window (`SESSION_RESTORE_TIMEOUT_MS`). Setup (`/session/new`), auth, and non-session pages default to Home (`/`).
5. **App-Like Back Navigation**: `OnBackPressedCallback` intercepts Back gestures:
   - Root `/` exits app (`finish()`).
   - Tab roots (`/dashboard`, `/climbs`, `/profile`, `/session/new`) navigate to `/` and clear history.
   - In-flow pages step back via `webView.goBackOrForward(step)`, automatically skipping over any `/login` or `/register` history entries.
   - Navigating away from auth pages clears WebView history.
6. **Compatibility**: Supports Android 15+ (enforced edge-to-edge, `targetSdk = 35`) while remaining backward compatible to `minSdk = 26` (Android 8.0).
