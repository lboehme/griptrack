# GripTrack Android On-Device Smoke Checklist (#99 / PRD #93)

**Test Date**: 2026-08-18  
**Target Hardware**: Samsung Galaxy S22 Ultra (SM-S908B), Android 16 (arm64-v8a)  
**App Build**: `app-debug.apk` (Chaquopy 17.0.0, CPython 3.13, FastAPI + SQLite)  

---

## 1. Prerequisites & Build Verification

- [x] **Gradle Build**: `./gradlew assembleDebug` builds `app-debug.apk` with zero errors.
- [x] **Lint & Tests**: `scripts/lint` clean (Ruff, Mypy, Pip-audit), `scripts/test` 243/243 passed.
- [x] **APK Installation**: `adb install -r app/build/outputs/apk/debug/app-debug.apk` streams and installs successfully.

---

## 2. On-Device Lifecycle & Startup Smoke Tests

| # | Step | Expected Result | Verified Result | Status |
|---|------|-----------------|-----------------|--------|
| 1 | **Clean Cold Start** | Splash screen appears with brand accent (`#E8532C`) and progress spinner; background daemon boots CPython 3.13 and uvicorn on `127.0.0.1:8000`; health poller checks `/health` until 200 OK. | Cold start completed in ~1.6s. Uvicorn bound, `/health` returned 200 OK, transitions to root landing screen. | **PASS** |
| 2 | **First-Run Registration** | Empty database creates user as `is_admin=1` with default starter grip types seeded; session cookie set and stored in `CookieManager`. | Account `lboehme@mailbox.org` created, verified `is_admin=1` in `users` table. | **PASS** |
| 3 | **Session Persistence Across Force-Stop** | Force-stopping app via `adb shell am force-stop org.griptrack.app` and relaunching retains session cookie and opens dashboard without prompting for login. | Session cookie flushed on pause/navigation; relaunch loaded `GET /` directly into dashboard ("Hey Lukas 👊"). | **PASS** |
| 4 | **Single Server Instance on Resume** | Backgrounding app (Home button) and resuming reconnects to the existing server process without port conflict or duplicate Python daemon. | Single process verified; server continues running and WebView reconnects instantly. | **PASS** |

---

## 3. Core Feature Flow Smoke Tests

| # | Step | Expected Result | Status |
|---|------|-----------------|--------|
| 5 | **Focus Session & Set Logging** | Start training session (`/session/new`), select grip type, log work sets (weight, reps, RPE, hold time), click Finish session. | **PASS** |
| 6 | **Max Test Logging** | Navigate to `/max-tests`, log a single-hand or two-hand max pull; verify estimated session maxes update. | **PASS** |
| 7 | **Boulder / Route Logging** | Navigate to `/climbs`, record a send/attempt with grade and style. | **PASS** |
| 8 | **Analytics & Chart Rendering** | Navigate to `/dashboard`; client-side `uPlot` chart loads and renders training volume series without JS errors. | **PASS** |
| 9 | **Data Export & File Chooser** | Navigate to `/profile`; click "Download data export (.zip)" — download worker fetches from loopback and saves `griptrack-export.zip` to Downloads; file picker opens on "Restore from export". | **PASS** |
| 10 | **Airplane Mode (100% Offline)** | Turn on airplane mode (disconnect Wi-Fi and mobile data); browse all pages, log sets, and view charts. | **PASS** |

---

## 4. Architecture Verification Notes

1. **Loopback Consistency**: App uses `127.0.0.1:8000` exclusively; same-origin CSRF checks pass consistently on all form submissions.
2. **App-Private Storage**: SQLite DB (`griptrack.db`) and `session_secret` reside in `/data/user/0/org.griptrack.app/files/` with secure file permissions (`0600`).
3. **Template & Asset Bundling**: All Jinja templates, CSS, JS (`htmx.min.js`, `uPlot.iife.min.js`, `client-date.js`), and Alembic migrations unpack to device disk and resolve with zero runtime missing-file errors.
