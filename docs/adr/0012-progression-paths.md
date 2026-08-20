# Progression is a selectable per-combo policy on top of the RPE trigger, not a fixed rule

ADR-0011 established Wave 4's autoregulation as an RPE-driven nudge that suggests
"add the smallest loadable increment" when you're ready. That single rule is only
*one* way to progress. This ADR records the decision to generalize it into three
selectable **progression paths**, so the nudge tells you what to change according
to a scheme you chose — not always "add weight."

The RPE readiness gate from ADR-0011 is the **trigger** (when you're ready to
advance / when to hold). The progression path is the **policy** (what "advance"
means). One path is active per combo, so there is never conflicting advice.

## Decision

**Each (hand, grip, edge) runs one of three progression paths; the RPE trigger
decides readiness, the path decides the step. Config is stored; phase is derived
from WorkSet history.**

Three paths:

- **Set progression** — weight and reps fixed; when ready, the nudge is
  "add a set." Grows volume by set count.
- **Weight progression** — sets and reps fixed; when ready, the nudge is
  "+ one loadable increment" (`plates.loadable_ladder`). This is ADR-0011's
  original rule, now recognized as just one path, and the **default**.
- **Double progression** — a two-step cycle over a user-set rep range
  (default 5–10):
  1. *Build reps:* weight fixed; when ready, "+1 rep" until **every** working set
     reaches the top of the range.
  2. *Build weight:* "+one loadable increment"; keep loading session over session
     while reps stay **above the range minimum** (reps fall naturally as weight
     climbs).
  3. *Reset:* once reps fall **to the minimum**, that weight is the new baseline —
     return to step 1 and rebuild reps at the heavier weight.

Cross-cutting rules:

- **RPE is the shared safety gate on every path.** You only advance when the last
  session hit its target at RPE ≤ 7; RPE ≥ 9 or a missed target holds you, on all
  three paths. The path's rep floor/ceiling drives progress; RPE only ever *stops*
  you early, never pushes past your chosen range.
- **Set cap.** Set progression grows to a user-set max (default 6). At the cap the
  nudge does not go silent — it suggests **"add weight and reset to baseline
  sets."** This is a one-tap suggestion, never an automatic scheme switch (honors
  ADR-0011's suggest-never-act). A retest is not triggered here; retests are
  earned by CurrentMax drift over time (the 8-week-floored retest nudge, ADR-0011).
- **Selection is per combo, set only in settings.** The path, rep range, and set
  cap are chosen in the "Configure training sessions" card, with a user-level
  default (Weight). There is **no session-start override** — changing a scheme is
  a deliberate act, not a mid-session tap.
- **Config stored, phase derived.** A `progression_settings` row stores path, rep
  target/range, and set cap per (user, grip, edge), with a null-combo row as the
  user default (mirroring `TrainingProtocol`'s null-user default). The current
  phase (building reps vs building weight, ready vs hold) is **computed from
  recent WorkSet history**, not stored — consistent with CurrentMax, trend, and
  asymmetry, and impossible to desync from the log.

## Why

- **Weight-only progression is the least useful default for finger training.**
  Rep-range and volume manipulation matter as much as load; offering only "add
  weight" ignores how climbers actually build finger strength. The three paths
  cover the schemes in common block-pull/no-hang programming.
- **Path-as-policy resolves the "two coaches" risk.** The earlier objection to
  progression logic was that a scheme and the autoregulation nudge could
  contradict each other. Making the path the *only* source of the step, gated by
  the *shared* RPE trigger, means exactly one suggestion at a time.
- **Deriving phase keeps the codebase honest.** GripTrack already derives every
  training signal from the WorkSet log rather than storing mutable state. A stored
  progression state machine could drift from edited/voided history; a derived one
  cannot.
- **No auto-switching, ever.** At the set cap the app suggests but never silently
  converts your scheme — the same discipline that governs every other nudge.

## Consequences

- New `progression_settings` table (migration): `(user_id, grip_type_id
  nullable, edge_mm nullable, path, rep_min, rep_max, max_sets)`; null grip/edge =
  the user's default. Weight/Set paths use a single rep target (rep_min == rep_max);
  Double uses the range.
- The rep target from ADR-0011 (`TrainingProtocol.base_work_set_reps`) becomes the
  fallback default; a combo's `progression_settings` overrides it, and Double
  reinterprets it as a range.
- The autoregulation nudge (ADR-0011) surfaces the path-defined step; its inline,
  passive, non-pre-filling presentation is unchanged.
- Deriving the double-progression phase requires a precise read of recent history
  (rep counts vs range, whether weight just changed); this is the state machine's
  real complexity and lives in `backend/analytics.py` (or a dedicated
  progression module) behind the HTTP seam, thresholds as named constants.
- Per-user protocol overrides (ADR-0005's IOU) are now genuinely exercised, per
  combo, for progression — the additive path that ADR-0005 anticipated.
