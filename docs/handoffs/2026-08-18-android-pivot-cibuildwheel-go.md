# GripTrack — session handoff (2026-08-18)

Fresh-agent handoff. This session **overturned the #97 Chaquopy NO-GO**: it
cross-compiled GripTrack's two Rust deps into Android arm64 wheels with
`cibuildwheel` and proved them running on the owner's phone, then implemented
**#108** (drop bcrypt for stdlib PBKDF2). Ends with #108 done + committed on a
branch, nothing pushed.

Repo: `/Users/lukas/Code/GripTrack_AI`. GitHub: `lboehme/griptrack` (private).
Read `CLAUDE.md` + `CONTEXT.md` first; the Android-pivot roadmap is in
`CLAUDE.md`. Prior handoff: `docs/handoffs/2026-08-14-android-pivot-chaquopy-nogo.md`
(the NO-GO this session reversed).

---

## 1. What got done this session

### #97 — cibuildwheel fallback → **GO** (issue closed)
The 2026-08-14 NO-GO was: `bcrypt==5.0.0` and `pydantic-core==2.46.4` have no
Chaquopy prebuilt Android wheels. This session built them ourselves and proved
them on-device. Both PASS on the **Galaxy S22 Ultra (SM-S908B, Android 16,
arm64-v8a)** under Chaquopy 17.0.0 @ CPython 3.13:

```
PASS  bcrypt: bcrypt 5.0.0: hashpw/checkpw round-trip OK
PASS  pydantic_core: pydantic_core 2.46.4: SchemaValidator round-trip OK
```

Key findings (full write-up in `docs/android-feasibility.md`, verdict on #97):
- `cibuildwheel --platform android` runs on macOS arm64, **auto-installs the
  NDK via sdkmanager AND wires the Rust cross-linker itself**
  (`CARGO_TARGET_AARCH64_LINUX_ANDROID_LINKER`) — the linker worry was unfounded.
- Wheels are `cp313` (auditwheel-confirmed **not abi3**), built against
  *official* CPython-Android 3.13.14, yet import + run fine under Chaquopy's
  *own* CPython 3.13.9 → **the "official-vs-Chaquopy C-ABI" crux is a
  non-issue**.
- `pydantic-core` built first try (maturin, no rust-toolchain pin, jiter 0.14
  from crates.io); the historical PyO3-datetime blocker does NOT reproduce.
- Chaquopy consumes local wheels via
  `pip { options("--find-links", file("wheels").absolutePath); install(...) }`;
  the app must move to Chaquopy **Python 3.13** (was 3.12).
- The `android/` probe scaffolding was **reverted** to the committed
  feasibility skeleton (Chaquopy 3.12, prod pins). The durable record is the
  doc + the #97 comments, not a modified skeleton.

### #108 — bcrypt → stdlib PBKDF2 (done, committed on branch)
Because every self-built wheel is per-release cross-compile maintenance,
dropping bcrypt halves that surface. `backend.auth` now hashes with stdlib
`hashlib.pbkdf2_hmac` (PBKDF2-HMAC-SHA256), self-describing
`pbkdf2_sha256$iterations$salt$hash`, 300k iterations, 16-byte
salt, `hmac.compare_digest`, fails closed on legacy/garbage hashes. Password cap
raised off bcrypt's 72 bytes → 1024. `bcrypt` removed from `requirements.txt`
**and uninstalled from the conda env**; `import backend.main` verified without
it. New **ADR-0009** records the decision + the reset-on-cutover migration.
**237 tests green, ruff+mypy+pip-audit clean.**

**Migration consequence:** existing bcrypt hashes can't be verified post-#108.
Reset-on-cutover — on the Fly deploy, current accounts need an admin reset /
re-register after this ships. The export/import archive carries no
`hashed_password`, so seeding the phone from an export is unaffected.

---

## 2. State of the tree / git

- Branch **`ticket-108-pbkdf2`** (off `main`), **committed, NOT pushed**. Three
  commits: the #97 GO doc, the #108 change, and the handoffs. `main` untouched;
  nothing on `origin`.
- `.polly/` is untracked local tooling — left alone, do not commit.
- Owner's next decision: push + PR the branch (and whether to run the usual
  dual review — GitHub Copilot + an Opus failure-hunting pass — per the
  `/orchestrate` end-of-batch convention), then merge, then decide on deploying
  (which triggers the reset-on-cutover for Fly accounts).

---

## 3. Immediate next actions (pick up here)

- **#98 — embed the real backend + WebView.** Now unblocked. After #108,
  **`pydantic-core` is the ONLY hard native wheel** the app must supply. Plan:
  bump the (real) app to Chaquopy Python 3.13, cross-compile the pydantic-core
  wheel (recipe below), feed it via `--find-links`, embed the FastAPI backend on
  `127.0.0.1`, run migrations on first launch (reproduces
  `docker-entrypoint.sh`), reach login in a WebView. Blocked-by #95/#96/#97 —
  all now satisfied (#97 GO). Then #99 (first-run/persistence/offline).
- **Push/PR #108** if the owner wants it landed (see §2).
- The other parallel tracks still stand: Wave 3 Asymmetry (#45–#48), #86, #91.

### Wheel rebuild recipe (toolchain already installed this session)
Installed on this Mac: rustup + `aarch64-linux-android` target; Android
cmdline-tools in `~/Library/Android/sdk` (ANDROID_HOME); `cibuildwheel` venv at
`~/griptrack-android-wheels/.venv`; Homebrew `python@3.13`; NDK 27.3.13750724
(auto-installed by cibuildwheel). Built wheels kept in
`~/griptrack-android-wheels/wheelhouse/`
(`bcrypt-5.0.0-cp313-…arm64_v8a.whl`, `pydantic_core-2.46.4-cp313-…arm64_v8a.whl`).

```bash
export ANDROID_HOME=~/Library/Android/sdk
export JAVA_HOME=/Library/Java/JavaVirtualMachines/temurin-17.jdk/Contents/Home
export PATH="$HOME/.cargo/bin:$PATH"
# fetch an sdist (avoid `pip download --no-binary` — it hangs building metadata;
# curl the sdist URL from https://pypi.org/pypi/<pkg>/<ver>/json instead), then:
~/griptrack-android-wheels/.venv/bin/cibuildwheel \
  --only cp313-android_arm64_v8a --output-dir wheelhouse <package-sdist-dir>
```

Gradle build of the `android/` project (Temurin JDK 17, NOT the AS-bundled JBR
25 which Gradle rejects):
```bash
cd android && JAVA_HOME=/Library/Java/JavaVirtualMachines/temurin-17.jdk/Contents/Home \
  ANDROID_HOME=~/Library/Android/sdk ./gradlew assembleDebug --console=plain
```
(don't `| tail` — a pipe masks gradle's exit code.) On-device probe:
`adb install -r app/build/outputs/apk/debug/app-debug.apk` →
`adb shell am start -n org.griptrack.app/.MainActivity` →
`adb logcat -s GripTrackFeasibility`.

---

## 4. Conventions / gotchas for this repo

- Test-first at the HTTP seam (`scripts/test`); lint `scripts/lint`
  (ruff+mypy+pip-audit); migrations via `scripts/new-migration` (never
  hand-write). Conda env `griptrack` (Python 3.14; separate from Chaquopy's
  3.13 buildPython). **bcrypt was uninstalled from this env this session** —
  that's intended (#108).
- Owner does NOT write code (built entirely by Claude Code). Terse-approval
  style. Confirm before outward/irreversible actions; commit/push only when
  asked.
- Bound every numeric/text input (`backend/limits.py`) + add a security test
  when adding routes.
- Memory updated this session:
  `~/.claude/projects/-Users-lukas-Code-GripTrack-AI/memory/android-pivot-orchestration-status.md`
  (has the GO verdict + #108 status).

## Suggested skills

- **`tdd`** — repo is strict test-first for #98 and any backend work.
- **`security-and-hardening`** — #108 touched the KDF; #98 embeds the backend on
  a loopback port (review the localhost-only binding + no external network).
- **`documentation-and-adrs`** / **`domain-modeling`** — keep ADRs + CONTEXT.md
  current as #98/#99 reshape the deployment story.
- **`orchestrate`** — if the owner batches the remaining parallel tickets
  (#45–#48, #86, #91).
