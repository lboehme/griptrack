# GripTrack — session handoff (2026-08-14)

Fresh-agent handoff. This session did PR #106 post-merge housekeeping, then went
deep on the **Android pivot's #97 Chaquopy feasibility** — building the APK on the
owner's Mac, hitting a NO-GO, and researching fallback options. Ends at a
**strategic decision point** the owner is weighing.

Repo: `/Users/lukas/Code/GripTrack_AI` (branch `main`, clean except one
uncommitted docs edit — see below). GitHub: `lboehme/griptrack` (private).
Read `CLAUDE.md` + `CONTEXT.md` first; the Android-pivot roadmap is in `CLAUDE.md`.

---

## 1. What got done this session

### Housekeeping after PR #106 merged
PR #106 carried no `Closes` reference, so nothing auto-closed. Closed manually
(each with a comment): PRDs **#87** (runtime slim) and **#100** (CSV import),
plus slices **#88, #89, #94, #95, #96, #101, #102**.

**Surprise finding — #103 and #104 were already implemented** as scope-creep
inside the #102 commit (`c9ee934`), not dispatched as tickets and not in PR #106's
stated scope. Verified against their acceptance criteria (import hardening caps +
`reverse_neutralize` in `backend/import_restore.py`; profile import UI + confirm
checkbox in `backend/templates/profile.html`; isolation/bounds tests in
`tests/test_security.py`). 30 tests green. Owner chose to close both with a
scope-creep caveat (they never got a standalone dual review). **Open risk:** #100
was closed on the strength of #103/#104 being complete — if a review ever finds
gaps, #100 should reopen too.

### #97 Chaquopy APK build → NO-GO
Built the `android/` Chaquopy skeleton for the first time on the owner's
Apple-silicon Mac. Toolchain fully cleared; the build reached Chaquopy's real
`pip` step and failed on wheel availability — **exactly the risk
`docs/android-feasibility.md` predicted**:
- `bcrypt==5.0.0` (Rust) → only pre-Rust C `3.2.2` in Chaquopy's repo.
- `pydantic-core==2.46.4` → only a `0.0.1` stub. (Surfaced via an isolation probe:
  temporarily pinned `bcrypt==3.2.2`, which downloaded cleanly, proving the
  Gradle/Chaquopy/pip plumbing works.)

Full verdict + the fallback-(1) research are recorded on **issue #97** and appended
to **`docs/android-feasibility.md`** — read those, don't re-derive. Decided at
build time on the host; the phone was never needed.

### Fallback (1) researched (not attempted)
Cross-compiling our own wheels via `cibuildwheel --platform android` (runs on
macOS): **plausible, not proven.** Both deps are PyO3/maturin Rust exts;
`pydantic-core` already builds for Android arm64 (Eutalix CI, Termux-targeted).
Requires bumping app Python 3.12→3.13 (cibuildwheel Android = PEP 738 = 3.13+;
Chaquopy 17 OK at 3.13.9). **Unverified crux:** official-CPython-Android vs
Chaquopy-CPython C-ABI match (`cp313`, not `abi3`) — only an empirical
build+install+import settles it. Details in `docs/android-feasibility.md` and on #97.

### Issue opened (do NOT implement yet)
**#108** — Replace bcrypt (Rust) with stdlib PBKDF2. Scoped, gated on the
strategic direction below. Removes half the native-wheel surface. `pydantic-core`
is the hard one (engine under Pydantic v2 / SQLModel; can't be cheaply removed).

---

## 2. The open strategic decision (where the owner is right now)

How to get GripTrack running on the phone, given the Chaquopy NO-GO. Options
discussed, cheapest-bet-first:

1. **pydantic-core cibuildwheel spike** — bounded (~1–3 days), binary outcome. If
   the ABI matches, the *entire existing app + 203 tests run unchanged*. Cheap bet
   to try first. Cheap-first sub-plan: build **bcrypt only** first (after #108),
   wire via `--find-links` at Python 3.13, load on the S22 — one result answers the
   ABI question before touching pydantic-core.
2. **Termux instead of Chaquopy** — no cross-compiling; Termux `pip install`s
   normally and prebuilt Termux arm64 wheels exist. Cheapest *working* path. Cost:
   not a one-tap APK ("install Termux, run a start script"). Not yet researched in depth.
3. **React Native rewrite** — reimplements ALL Python logic in TS (domain logic,
   analytics math, SQLite + migrations, every screen, new test suite, native build
   pipeline). ~an order of magnitude more work (weeks–months) but permanently kills
   the whole "Python on a phone" problem class and yields a real native app. My
   advice given to owner: don't start RN to *avoid* the pydantic-core spike (the
   spike is far cheaper to try first); start RN only when a real native app is the
   goal for its own sake.
4. **LAN self-host** — backend on an always-on home box; phone is just the PWA. No
   Android Python at all, but reintroduces "a server."

**Last thing I asked the owner:** whether to capture the "native rewrite vs
embedded Python" trade-off as an ADR or PRD-style issue. Awaiting their answer.

---

## 3. Immediate next actions (pick up here)

- **Await the owner's steer** on the strategic decision above before doing heavy
  work. Don't start the RN rewrite or the cibuildwheel build unprompted.
- If they say record the decision: draft an **ADR** ("native rewrite vs embedded
  Python for on-device GripTrack") and/or a PRD issue. Use the `documentation-and-adrs`
  / `domain-modeling` skill; ADRs live in `docs/adr/` (0008 is the highest so far).
- If they greenlight the **pydantic-core / bcrypt spike**: implement #108 first
  (`tdd` skill, tests at the HTTP seam), then the cibuildwheel path per
  `docs/android-feasibility.md`. Needs NDK + Rust `aarch64-linux-android` +
  `cibuildwheel`; bump `android/app/build.gradle.kts` `version` to `"3.13"`.
- If they pick **Termux**: research the packaging path properly first (a
  `research`-skill background agent is a good fit) before building.

### Environment state (already installed this session)
- **Temurin JDK 17** at `/Library/Java/JavaVirtualMachines/temurin-17.jdk/Contents/Home`
  (the AS-bundled JBR is 25, which Gradle 8.9 rejects — always use 17 for this build).
- **Homebrew `python3.12`** at `/opt/homebrew/bin/python3.12` (Chaquopy's `buildPython`).
- Android Studio + `adb` present; **Android SDK NOT yet installed** (first-run
  wizard not completed — SDK dir empty). Owner's phone: **Galaxy S22 Ultra** (arm64,
  target device; USB-debugging setup not yet confirmed connected).
- Re-run the Chaquopy build with:
  `cd android && JAVA_HOME=/Library/Java/JavaVirtualMachines/temurin-17.jdk/Contents/Home ANDROID_HOME=~/Library/Android/sdk ./gradlew assembleDebug --console=plain`
  (**don't `| tail`** — a pipe masks gradle's real exit code; this bit me once.)

### Uncommitted change to be aware of
`docs/android-feasibility.md` has an appended "on-device outcome" + "fallback (1)
research" section, **uncommitted** in the working tree. Owner hasn't asked to
commit. `android/app/build.gradle.kts` was reverted to production pins (working
tree clean there).

---

## 4. Conventions / gotchas for this repo

- All tests at the HTTP seam (`scripts/test`). Lint: `scripts/lint`
  (ruff+mypy+pip-audit). Migrations via `scripts/new-migration` (never hand-write).
  Conda env `griptrack` (note: it's Python **3.14**, not 3.12 — separate from
  Chaquopy's buildPython).
- Owner does **not** write code (built entirely by Claude Code). Terse-approval
  style. Confirm before outward/irreversible actions.
- Bound every numeric/text input (`backend/limits.py`) + add a security test when
  adding routes.
- `/browse` (gstack) is referenced in global config but **NOT installed in this
  session** — use `WebSearch`/`WebFetch` for web research (load via ToolSearch).
- Memory files updated this session:
  `~/.claude/projects/-Users-lukas-Code-GripTrack-AI/memory/` — see
  `android-pivot-orchestration-status.md` (has the #97 verdict + fallback-1 note)
  and `conda-miniforge-arm64.md`.

---

## Suggested skills

- **`documentation-and-adrs`** — if the owner wants the native-vs-embedded decision
  recorded as an ADR (`docs/adr/`, next is 0009).
- **`domain-modeling`** — for writing/updating the ADR + keeping `CONTEXT.md` current.
- **`research`** — to investigate the Termux packaging path (option 2) against
  primary sources and capture findings as a repo doc, if that path is chosen.
- **`tdd`** — for #108 (bcrypt→PBKDF2) and any implementation work; repo is strict
  test-first at the HTTP seam.
- **`security-and-hardening`** — the #108 password-hashing change is security-
  sensitive (KDF choice, migration, `limits.py` bound, timing-equalized auth).
- **`orchestrate`** — only if the owner returns to batching several ready-for-agent
  issues (Wave 3 Asymmetry #45–#48, etc.); not relevant to the current Android fork.
