# Android Chaquopy feasibility (#97)

Status: **skeleton scaffolded, on-device verification not yet run.** This
document is honest about that split — everything under "Verified in this
session" was checked against primary sources from the machine that wrote
this skeleton (no Android SDK, no device, no emulator available there).
Everything under "The owner's remaining step" requires a real arm64 device
and hasn't been run by anyone yet.

## What #97 is proving

[PRD #93](https://github.com/lboehme/griptrack/issues/93) wants GripTrack
running entirely on-device via Chaquopy (embedded CPython) + a WebView. The
biggest named risk in that PRD is whether GripTrack's two Rust-backed
runtime dependencies — **`bcrypt`** (password hashing, `backend.auth`) and
**`pydantic-core`** (every Pydantic/SQLModel model, i.e. almost every
request) — can even be installed and run under Chaquopy on Android arm64.
#97 exists to answer that *before* any shell/WebView work (#98) is built on
top of an assumption that might not hold.

The `android/` project in this repo is deliberately narrow: it does **not**
embed the FastAPI backend, does **not** open a WebView, and has **no
network permissions**. It's a single-screen app that starts the embedded
Python 3.12 interpreter and runs two checks
(`android/app/src/main/python/feasibility_check.py`):

1. `import bcrypt`, then a real `bcrypt.hashpw()` / `bcrypt.checkpw()`
   round-trip.
2. `import pydantic_core`, then build a `SchemaValidator` and validate a
   value through it.

Both PASS/FAIL results are shown on screen and logged to Logcat under the
tag `GripTrackFeasibility`.

## Pinned versions, and why

| Component | Version | Source |
|---|---|---|
| Chaquopy Gradle plugin | **17.0.0** (2025-12-01) | [Chaquopy version summary](https://chaquo.com/chaquopy/doc/current/versions.html); [changelog](https://chaquo.com/chaquopy/doc/current/changelog.html) |
| Chaquopy-supported AGP range | 7.3.x – 9.2.x | Same as above |
| Chaquopy runtime Python versions | 3.10.19, 3.11.14, **3.12.12**, 3.13.9, 3.14.0 | Same as above |
| Chaquopy min `minSdk` | 24 | Same as above |
| App Python version | **3.12** | Matches `backend/` (project targets Python 3.12 per repo `CLAUDE.md` / PRD #93) and is within Chaquopy 17.0's supported range |
| Android Gradle Plugin | **8.7.0** | [AGP 8.7.0 release notes](https://developer.android.com/build/releases/agp-8-7-0-release-notes) — requires Gradle 8.9, JDK 17. Chosen well inside Chaquopy's tested 7.3–9.2 range rather than at the edge (9.2), since Chaquopy's own docs are the less frequently updated of the two projects. |
| Gradle | **8.9** | Required by AGP 8.7.0 (see above) |
| `bcrypt` (pip target) | **5.0.0**, exact match to `requirements.txt` | [`bcrypt` CHANGELOG](https://github.com/pyca/bcrypt/blob/main/CHANGELOG.rst) — bcrypt has been implemented in Rust (via PyO3) since 4.0.0 |
| `pydantic-core` (pip target) | **2.46.4**, the exact version `pydantic==2.13.4` (the `requirements.txt` pin) depends on | Verified via `https://pypi.org/pypi/pydantic/2.13.4/json` → `requires_dist` |
| App `minSdk` / `compileSdk` / `targetSdk` | 26 / 35 / 35 | Reasonable current values, not load-bearing to the feasibility question |
| ABI filter | **arm64-v8a only** | Matches #97's "builds an installable arm64 APK" acceptance criterion. `x86_64` is deliberately excluded — running only on the emulator would let an arm64-specific wheel problem go undetected. |

## The actual risk: prebuilt-wheel availability (verified 2026-08-13)

Chaquopy resolves pip installs against its own hosted repository of
Android-tagged wheels first
(`https://chaquo.com/pypi-13.1/<package>/`, confirmed as the current index
via `chaquo/chaquopy` GitHub discussion; the older `pypi-7.0` URL is
retired). If a package isn't there and has no pure-Python sdist that
happens to build cleanly, `pip install` fails at Gradle build time —
**before** you'd even get to a device. This is why the go/no-go can
partly be answered by `./gradlew assembleDebug` alone.

Directly inspecting that repository (`curl -s
https://chaquo.com/pypi-13.1/bcrypt/` and the repo root listing) turned up
two load-bearing facts:

- **`bcrypt`**: Chaquopy hosts prebuilt wheels only up to **3.2.2**
  (`bcrypt-3.2.2-0-cp312-cp312-android_21_arm64_v8a.whl`, dated
  2023-12-05, and a `cp313`/API-24 build dated 2024-10-22). **3.2.2
  predates bcrypt's 4.0 rewrite from C to Rust** — so this prebuilt wheel
  does *not* demonstrate that the Rust `_bcrypt` extension (what
  `requirements.txt` actually pins, `bcrypt==5.0.0`) builds or runs under
  Chaquopy. It only proves the old, unrelated C implementation does.
- **`pydantic-core`**: **absent entirely** from Chaquopy's prebuilt
  repository — no `pydantic`, `pydantic-core`, `pydantic_core`, `jiter`,
  `maturin`, or `rust` directory exists at any level of the index (checked
  by listing the full repo root and grepping for these names). This lines
  up with two real, unresolved GitHub issues:
  - [chaquo/chaquopy#1326](https://github.com/chaquo/chaquopy/issues/1326) —
    a user on Chaquopy 16.0.0/Python 3.12 tried to hand-build
    `pydantic-core` and hit its `jiter` dependency resolving via the Cargo
    registry instead of a locally-built wheel; closed with no resolution
    recorded.
  - [pydantic/pydantic-core#1607](https://github.com/pydantic/pydantic-core/issues/1607) —
    building `pydantic-core` 2.27.2 for Chaquopy failed because required
    PyO3 datetime API types (`PyDate`, `PyDateTime`, `PyDelta`, …) weren't
    available in Chaquopy's PyO3 build environment; closed as duplicate,
    no fix linked.
  - A Termux-focused project,
    [Eutalix/android-pydantic-core](https://github.com/Eutalix/android-pydantic-core),
    does publish prebuilt `pydantic-core` wheels for Android arm64 —
    **but it targets Termux specifically** and "hardcodes Termux library
    paths (`/data/data/com.termux/files/usr/lib`)"; it is not
    Chaquopy-ABI-compatible and shouldn't be dropped in as-is.

**Conclusion going in:** `bcrypt==5.0.0` and `pydantic-core==2.46.4` (what
`android/app/build.gradle.kts` actually requests, matching production
`requirements.txt`) have **no confirmed prebuilt Chaquopy wheel today**.
The `pip {}` block is configured to request them anyway — a failed
`./gradlew assembleDebug` pip-resolution step *is itself* the answer this
ticket is asking for, not a sign the project is misconfigured. This is
exactly the situation PRD #93 called out: *"we deliberately did not gate
this spec behind a throwaway spike... if either can't be made to work
under Chaquopy, revisit the approach before building the shell."*

cibuildwheel gained official Android target support in v3.1.0 (per
[cibuildwheel's docs](https://cibuildwheel.pypa.io/)), which is the
currently-recommended way to hand-build newer Android wheels for Chaquopy
per the [Chaquopy pypi builder README](https://github.com/chaquo/chaquopy/blob/master/server/pypi/README.md).
That path exists but is unexplored — see "If the result is NO-GO" below.

## Verified in this session (no device involved)

- Chaquopy plugin version, Python support matrix, AGP range, `minSdk`
  floor — read directly from Chaquopy's own docs (URLs above).
- AGP 8.7.0 → Gradle 8.9 → JDK 17 compatibility — read directly from the
  AGP release notes.
- `bcrypt==5.0.0` is what `requirements.txt` pins today; `pydantic-core`
  is what `pydantic==2.13.4` in `requirements.txt` actually resolves to
  (`2.46.4`) — read from PyPI JSON metadata.
- Chaquopy's prebuilt-wheel repository contents for `bcrypt` (full
  directory listing) and the repo root (full listing, grepped) — fetched
  and inspected directly.
- `android/gradle/wrapper/gradle-wrapper.jar` and the `gradlew`/
  `gradlew.bat` scripts were fetched from the official `gradle/gradle`
  GitHub repository at tag `v8.9.0` (the same repo Gradle itself is built
  from) and the jar was confirmed to be a valid archive containing the
  expected `org.gradle.wrapper.*` classes.
- The Gradle/Chaquopy/AGP files were cross-checked by hand for internal
  consistency (matching plugin ids, matching Python/AGP/Gradle version
  triples, matching ABI filters, matching package/namespace strings) —
  **not** by actually running Gradle, since no JDK 17, Android SDK, or
  Gradle installation was available in the environment that wrote this.

## The owner's remaining step (not yet done by anyone)

Nobody has built this APK or run it on a device yet. That's the real
verification this ticket is for, and it can only happen on the owner's
machine/phone:

1. **Prerequisites:** Android Studio (current stable channel bundles JDK
   17 already), a physical or virtual arm64-v8a Android device/emulator
   at API 26+ with developer mode / USB debugging enabled (physical
   device strongly preferred — an arm64 *emulator* on an Apple-silicon
   Mac host can mask ABI-specific problems a real ARM chip would surface,
   and vice versa on x86 hosts an arm64 emulator is slow but still valid).
2. Open the `android/` directory as a project in Android Studio (**not**
   the repo root — `android/` is a self-contained Gradle project).
   Let it sync. **This sync IS the first go/no-go signal**: if the
   `chaquopy { pip { install(...) } }` step can't resolve `bcrypt==5.0.0`
   or `pydantic-core==2.46.4` for `arm64-v8a`/Python 3.12, the build fails
   here with a pip error, before touching a device.
3. If sync/build succeeds: `Run ▸ Run 'app'` with a connected arm64
   device, or from a terminal inside `android/`:
   ```
   ./gradlew assembleDebug
   adb install -r app/build/outputs/apk/debug/app-debug.apk
   adb shell am start -n org.griptrack.app/.MainActivity
   ```
4. **Read the result** two ways (they should agree):
   - On screen: the app shows one `PASS`/`FAIL` line per check plus a
     final `GO`/`NO-GO` line.
   - In Logcat: `adb logcat -s GripTrackFeasibility` (or the Logcat pane
     in Android Studio filtered to that tag) shows the same lines, plus
     the full Python traceback on any `FAIL`.
5. **Record the outcome on issue #97** (`gh issue comment 97 --repo
   lboehme/griptrack --body "..."`) — both the PASS/FAIL lines and
   whichever stage (Gradle sync vs. on-device run) it happened at.

## Go/no-go criteria

**GO** only if *all* of:
- `./gradlew assembleDebug` succeeds (both packages resolve as
  arm64-v8a/cp312 wheels — whether from Chaquopy's own repo or wherever
  pip finds them).
- The app launches without crashing.
- `check_bcrypt` shows `PASS` (import succeeds, `hashpw`/`checkpw`
  round-trip returns true).
- `check_pydantic_core` shows `PASS` (import succeeds, `SchemaValidator`
  round-trip returns the validated value).

**NO-GO** — stop and revisit the approach before starting #98 — if any of
the above fails, including a pip-resolution failure at build time. Per
PRD #93's own framing, a NO-GO on either package means: *"if either can't
be made to work under Chaquopy, revisit the approach before building the
shell."*

### If the result is NO-GO

In rough order of effort:

1. **Isolate which package, and whether it's a plumbing problem or a
   package problem.** Temporarily change the `bcrypt` pip line to
   `install("bcrypt==3.2.2")` — the version confirmed to have a Chaquopy
   prebuilt wheel — and rebuild. If *that* succeeds and shows PASS, the
   Gradle/Chaquopy plumbing itself is fine and the problem is specific to
   the Rust-based `bcrypt` (4.x+) and/or `pydantic-core`. If even 3.2.2
   fails, something more basic is wrong with the project setup itself.
2. **Try `cibuildwheel`'s Android target** (v3.1.0+,
   https://cibuildwheel.pypa.io/) on a Linux x86_64 or macOS host to
   hand-build `bcrypt==5.0.0` and/or `pydantic-core==2.46.4` wheels
   targeting Chaquopy's ABI, then feed them in via a local
   `--find-links` directory in the `pip {}` block
   (`install("-r", "requirements.txt")` supports this per the Chaquopy
   pip docs). This is real, non-trivial cross-compilation work (a Rust
   toolchain targeting `aarch64-linux-android` is required) — budget
   accordingly.
3. **File/track upstream**, since this repo isn't the first to hit this:
   the two GitHub issues linked above are the existing paper trail for
   `pydantic-core`; there is no equivalent open issue yet for `bcrypt`
   4.x+ specifically, so that gap is worth reporting to
   `chaquo/chaquopy` if reached.
4. **Revisit the approach**, per PRD #93's explicit fallback framing —
   this is the scenario the PRD's "Option 4" (native rewrite) and the
   personal-instrument-scope ADR-0006 exist to make an acceptable, not
   catastrophic, outcome.

## Known Chaquopy + Rust-wheel caveats worth remembering later

- Chaquopy's own prebuilt-package repository is versioned independently
  of the plugin (currently `pypi-13.1`, not `pypi-17.0`) — don't assume
  the index version tracks the plugin version.
- 32-bit ABIs (`armeabi-v7a`, `x86`) lost Chaquopy support entirely for
  Python 3.12+ as of Chaquopy 16.0.0 — irrelevant here since this project
  targets arm64-v8a only, but relevant if `x86_64` emulator support is
  ever added back.
- For Python 3.13+, Chaquopy's own maintainers now point package authors
  at `cibuildwheel` rather than Chaquopy's legacy `build-wheel` tool for
  producing new native wheels; the legacy tool only runs on Linux x86-64.
