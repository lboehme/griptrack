# Wave 4 makes signals actionable through transparent nudges that suggest but never act

GripTrack collects RPE, work-set history, SessionMaxEstimates, and CurrentMax,
but until Wave 4 none of it fed a suggestion back to the user — "RPE is
collected and used for nothing" (issue #59). Wave 4 turns those signals into a
single coherent feature surface: RPE-driven autoregulation, retest and estimate
nudges, a mean-intensity trend series, and a real rest timer. This ADR records
the design settled in the #59 grill — chiefly *why the system suggests but never
acts*, and the thresholds chosen to keep nudges trustworthy rather than nagging.

## Decision

**Every Wave-4 signal is a transparent, deterministic Tier-1 nudge: it suggests
in plain sight, is dismissed with one tap, recomputes from live data (no stored
dismissal state), and never mutates the user's entered values or CurrentMax.**

- **RPE-driven autoregulation (per hand, opt-in via logging RPE):**
  For a given (hand, grip, edge), look at the last two sessions that trained it
  (deloads excluded). If *every* working set in both hit the user's target at
  RPE ≤ 7, show a passive inline hint on the work-set card suggesting the next
  step. **What that step is depends on the combo's progression path (ADR-0012)** —
  add a set, add a loadable increment, or add a rep; this ADR is the *trigger*
  (when you're ready / when to hold), ADR-0012 is the *policy* (what to change).
  RPE ≥ 9, or a set below target, only **withholds the up-hint** ("hold here") —
  the system never suggests a lower weight. A working set with no RPE makes the
  session ineligible and the hint stays silent. The hint is text only; it never
  pre-fills the stepper.
- **Rep target is now per-user (cashes the ADR-0005 IOU):**
  `base_work_set_reps` moves from a global-only value to a per-user
  `TrainingProtocol` row written from a new "Configure training sessions"
  settings card. Comparing against a hard-coded 5 would misfire for anyone
  training intentional low-rep days; the rule reads the user's own target so it
  stays legible ("hitting your 5-rep target easily → go up").
- **Retest nudge — gated by a time floor, not just drift:**
  Fire only when CurrentMax has drifted **≥ one loadable increment** above the
  last MaxWeightTest **and** it has been **≥ 8 weeks (56 days)** since that test.
  The 8-week floor is the load-bearing decision: without it the nudge fires the
  instant any work set beats the test, nagging users to retest on noise. Eight
  weeks lets real training progress accumulate so a retest measures a trend, not
  a good day.
- **Estimate nudge:**
  Fire when a combo with no MaxWeightTest has accumulated a SessionMaxEstimate in
  **3 distinct sessions** — "you've estimated this 3×, do a guided test?"
- **Nudge presentation is non-intrusive by construction:**
  Reflective nudges (retest, estimate) render as at-most-one dismissible banner
  at **session start** for the combo about to be trained (retest wins if both
  qualify) — never a modal, never the dashboard. The autoregulation hint renders
  inline on the card. All nudges are **ephemeral**: no dismissal-state table; a
  dismissed nudge simply stops firing once its condition clears (you retest, or
  stop re-estimating) and reappears otherwise, which is correct behavior for a
  retention feature.
- **Mean-intensity series:**
  Plot per-session mean intensity — the simple mean of each working set's
  `weight ÷ compute_current_max(as_of=session.date)` for the combo/hand — as a
  second series on a **secondary right-hand axis** of the existing per-combo
  uPlot trend chart, drawn together with tonnage (never a toggle). The two
  curves shown together are the whole point: intensity climbing while trimmed
  volume looks flat is progress that would otherwise read as a plateau. Points
  where CurrentMax is None (untested/estimate-only) are skipped.
- **Rest timer — device-gated, storage-deferred:**
  Replace the throwaway client-only countdown (#82) with a real timer: a
  Screen Wake Lock so the phone doesn't sleep mid-rest, and a default duration
  configurable in the "Configure training sessions" card
  (`TrainingProtocol.default_rest_seconds`). No audio (native Android target, no
  web). Actual rest durations are **not persisted** — nothing in Wave 4 reads
  them, and storing with no consumer is speculative schema; add it when the
  injury guardian (#28) or a rest-aware signal needs it.

## Why

- **Suggest-but-never-act preserves trust and matches CurrentMax's existing
  conservative bias.** CurrentMax already nudges rather than auto-adjusts; a
  Tier-1 system that silently changed loads or auto-retested would undermine the
  transparency that makes deterministic autoregulation defensible over an opaque
  AI coach.
- **A step-down suggestion on one bad day feels punishing.** Withholding the
  up-hint communicates "hold" without judgement; whether to deload is the
  athlete's call, informed by the deload flag they already control.
- **The 8-week retest floor is the difference between a signal and a nag.**
  Owners explicitly do not want frequent retests in short windows — a retest is
  only meaningful when enough training has happened to move the true max, so the
  nudge measures progress instead of celebrating noise.
- **Ephemeral nudges keep the schema and the UX honest.** No dismissal table to
  maintain or migrate, and a condition-driven nudge can't get stuck "dismissed"
  while the underlying problem persists.
- **Per-hand autoregulation is the point of an asymmetry-aware app.** Left and
  right diverge; a single combined suggestion would erase exactly the signal
  Wave 3 was built to surface.

## Consequences

- `TrainingProtocol` gains `default_rest_seconds` (migration) and starts being
  written per-user; `get_protocol` already prefers a per-user row, so no lookup
  change is needed. Per-user protocol overrides (ADR-0005's deferred IOU) become
  real for the rep target and rest duration — other protocol fields stay global
  until a surface needs them.
- Autoregulation depends on RPE being logged; the wake-at-7 default hint (#114)
  becomes load-bearing, since accepting the prefilled 7 counts as logging RPE.
- Two same-day sessions count as two distinct sessions for the "last two"
  window (they are separate `TrainingSession` rows).
- The nudge thresholds (retest 8-week floor, estimate count of 3, autoregulation
  RPE ≤ 7 / ≥ 9) live as named constants alongside the analytics thresholds in
  `backend/analytics.py`, tunable without touching call sites.
- Rest-gap analytics remain deferred: `TrainingSession.started_at` still exists
  for that future, but no per-set rest duration is stored yet.
