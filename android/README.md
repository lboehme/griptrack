# GripTrack Android shell — Embedded Backend + WebView (#98)

This is the Android shell for GripTrack, packaging the embedded FastAPI backend,
SQLite database, Jinja templates, static assets, and Alembic migrations via
**Chaquopy 17.0.0** (CPython 3.13) behind a native Android **WebView** (PRD #93).

## Architecture

1. **Embedded Python server (`ServerManager.kt` + `backend.launcher`)**:
   - Spawns a daemon background thread at app cold-start running CPython 3.13.
   - Runs `backend.launcher.serve(app_dir, host="127.0.0.1", port=8000)`:
     - Sets the SQLite DB path to an app-private location (`filesDir/griptrack.db`).
     - Executes Alembic migrations (`upgrade head`) to establish schema and seed data.
     - Provisions a persistent session secret (`filesDir/session_secret`).
     - Binds `uvicorn` on loopback `127.0.0.1:8000` with the plain ASGI runner (`asyncio`/`h11`).
     - Sets `GRIPTRACK_WEBVIEW_BUILD=1` (skipping service worker and manifest).
   - Polls `http://127.0.0.1:8000/health` until HTTP 200 is returned.

2. **Native WebView & Splash UI (`MainActivity.kt` + `activity_main.xml`)**:
   - Shows a branded splash screen (`#E8532C`) while the server boots and migrations run.
   - Once `/health` returns 200, displays the WebView loaded at `http://127.0.0.1:8000/login`.
   - Cleartext loopback traffic is allowed via `android:usesCleartextTraffic="true"`.
   - Javascript, DOM storage, and cookie persistence are enabled.
   - Preserves WebView history on Android back button presses (`OnBackPressedCallback`).
   - Server lifecycle survives Activity recreation and backgrounding.

## Prerequisites

- **JDK 17** (e.g. Temurin 17 at `/Library/Java/JavaVirtualMachines/temurin-17.jdk/Contents/Home`)
- **Android SDK** with Command-line Tools / Build-tools 35 (at `~/Library/Android/sdk`)
- **Python 3.13** on host (`/opt/homebrew/bin/python3.13`)
- `pydantic-core` arm64 cp313 wheel in `android/app/wheels/` (pre-bundled)

## Building the APK

From `android/` directory:

```bash
JAVA_HOME=/Library/Java/JavaVirtualMachines/temurin-17.jdk/Contents/Home \
ANDROID_HOME=~/Library/Android/sdk \
./gradlew assembleDebug --console=plain
```

The APK will be output at:
`android/app/build/outputs/apk/debug/app-debug.apk`

## Sideload & Run on Device

With an arm64-v8a Android device connected via USB with USB debugging enabled:

```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb shell am start -n org.griptrack.app/.MainActivity
```

Monitor logs:
```bash
adb logcat -s GripTrackServer GripTrackActivity
```

## Manual On-Device Smoke Checklist (PRD #93)

1. [ ] **Install APK**: Install `app-debug.apk` on a real arm64 device.
2. [ ] **Cold Start**: Launch app; splash screen appears with progress bar; switches to login screen on `127.0.0.1:8000`.
3. [ ] **First-run Registration**: Navigate to `/register`; enter email + password; submit. Account is created and becomes admin; session cookie is saved (no CSRF or cookie drop).
4. [ ] **Focus Screen**: Log a work set via the Focus screen.
5. [ ] **Dashboard Chart**: Open Dashboard; verify client-side uPlot TrainingVolume chart renders.
6. [ ] **Data Persistence**: Force-kill the app (`adb shell am force-stop org.griptrack.app`) and reopen. Confirm user remains logged in and data persists from SQLite DB.
7. [ ] **Airplane Mode**: Turn on airplane mode (no network connectivity); perform actions to confirm 100% offline, on-device operation.
