# GripTrack Android shell — Chaquopy feasibility skeleton (#97)

This is a Chaquopy (embedded CPython) Android Studio / Gradle project. Its
only job right now is to prove that `bcrypt` and `pydantic-core` — the two
Rust-backed dependencies GripTrack's backend needs — install and run on an
arm64 Android device under Python 3.12. It is **not** a throwaway spike:
this project skeleton is meant to become the real app shell in #98 (embed
the FastAPI backend + WebView).

Full rationale, sourced version pins, the native-wheel risk writeup, and
the go/no-go criteria live in
**[`../docs/android-feasibility.md`](../docs/android-feasibility.md)** —
read that before building. This file is just the quickstart.

## What's here

```
android/
├── build.gradle.kts              # root: declares AGP 8.7.0 + Chaquopy 17.0.0
├── settings.gradle.kts           # repositories, module list
├── gradle.properties
├── gradlew, gradlew.bat, gradle/wrapper/   # Gradle 8.9 wrapper
└── app/
    ├── build.gradle.kts          # namespace, arm64-v8a-only ABI filter,
    │                              # chaquopy { defaultConfig { version = "3.12"; pip {...} } }
    └── src/main/
        ├── AndroidManifest.xml   # single activity, no permissions
        ├── java/org/griptrack/app/MainActivity.kt
        ├── python/feasibility_check.py   # the actual bcrypt/pydantic_core probe
        └── res/…                 # one-screen layout + strings
```

`app/build.gradle.kts` pins `pip { install("bcrypt==5.0.0");
install("pydantic-core==2.46.4") }` — the exact versions
`backend/requirements.txt` pins today (`pydantic-core` via the pinned
`pydantic==2.13.4`), so this is a real test of the versions the app would
actually ship.

## Build & run (owner-only — needs Android Studio + a device)

This project was scaffolded and researched on a machine with **no Android
SDK, no Android Studio, and no arm64 device**, so nobody has run
`./gradlew assembleDebug` against it yet, and the on-device check has not
been performed by anyone. That verification is the remaining manual step.

1. Open the `android/` folder (this folder, not the repo root) in Android
   Studio. Let Gradle sync.
   - **This sync is already a go/no-go signal.** `docs/android-feasibility.md`
     found no confirmed Chaquopy prebuilt wheel for `bcrypt==5.0.0` (Rust,
     post-4.0) or `pydantic-core` at all — so a pip-resolution failure
     here is expected to be a live possibility, not a sign this project is
     broken.
2. If sync succeeds, run on a connected **arm64-v8a physical device**
   (strongly preferred over an emulator for this check — see the doc for
   why) via `Run ▸ Run 'app'`, or from a terminal:
   ```
   ./gradlew assembleDebug
   adb install -r app/build/outputs/apk/debug/app-debug.apk
   adb shell am start -n org.griptrack.app/.MainActivity
   ```
3. Read the result on screen (PASS/FAIL per check, GO/NO-GO overall) and
   in Logcat: `adb logcat -s GripTrackFeasibility`.
4. Record the outcome on issue #97, per the checklist at the end of
   `docs/android-feasibility.md`.

## Explicitly out of scope for this project (yet)

- No WebView, no embedded FastAPI server, no backend import — that's #98.
- No `x86_64` emulator ABI — arm64-v8a only, matching #97's acceptance
  criteria and to avoid an emulator masking an arm64-specific problem.
- No app icon assets, no theming beyond the AppCompat default — this is a
  feasibility probe screen, not app UI.
