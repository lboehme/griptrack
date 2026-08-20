# GripTrack

A mobile-first app for logging block-pull/no-hang finger-strength training and
climbing sends, with analysis of strength trends and their correlation to
climbing grade.

## Language

**TrainingSession**:
One logged workout visit: a date plus the work sets performed in it. Owns
many WorkSets. Exists in the database from the moment its first
warmup/ramp step is checked off — session-level interactions (notes,
deload flag, pain reports, warmup ticks) autosave immediately and there is
no final "submit" step, so a TrainingSession can be, and often briefly is,
incomplete. Its WorkSets arrive one Set commit at a time. A
(user, date) can hold more than one
TrainingSession — e.g. a morning and evening pull — distinguished by
`session_number` (1, 2, ...; default 1). `(user_id, date, session_number)`
is the identity key and must stay stable (future offline sync relies on
idempotent upserts against it). Default flows (start page, session-page
redirects) always resolve to the day's *latest* session_number; starting a
second session on today is an explicit affordance, and navigating to a
past date with no session at all requires an explicit "create one?"
confirmation rather than instantiating silently (issue #51).
_Avoid_: Session (ambiguous with the auth/login session), Workout, Training Log

**WorkSet**:
One set of the tracked work-set portion of a TrainingSession (hand,
grip_type, edge_mm, weight_kg, reps, set_number, rpe). Warmup/ramp sets are
never persisted as WorkSets — they're computed and shown, not logged.
_Avoid_: Set, Rep set

**Set commit**:
The single gesture that writes a set — the "Set done" button on the Focus
screen. Writes both hands' WorkSets for one set_number in one atomic
request (`POST /session/set`), or one hand's under a sequential
HandOrderPreference. Until it fires, the stepper values on screen are
unsaved client state, so the set does not exist. Replaced the old
per-cell autosave table, where each field saved on its own; see
`docs/adr/0007-set-commit-over-per-cell-autosave.md`.
_Avoid_: Save, submit (the screen has no form-submit model)

**Edit mode**:
The Focus screen's correction path. Tapping a row in the COMPLETED list
reloads that set's values back into the hand cards; the progress pill
reads "Editing set N" and the commit button becomes "Save" alongside a
Cancel. Saving takes the same Set commit path and returns focus to the
set the user was on. Exists so there is exactly one editing surface for a
WorkSet rather than a second, smaller one embedded in the completed list.
_Avoid_: Inline edit, edit form

**Loadable ladder**:
Every total weight a user's PlateInventory can actually make on the single
pin, in ascending order — the full achievable set that
`round_down_to_loadable` already computes internally and discards above
its target. The Focus screen's weight steppers walk this ladder one rung
per tap, so every reachable value is physically loadable. Embedded in the
page as JSON so taps stay instant and work offline. A starting value that
is off-ladder (a CurrentMax straight from a MaxWeightTest, or older
free-entry history) snaps to the next rung in the direction of travel;
both ends clamp. Bounded like every other numeric input, since the
subset-sum behind it is the DoS-sensitive path.
_Avoid_: Increment, step size (it is not a fixed step)

**MaxWeightTest**:
A dated record of the heaviest weight a user pulled for one specific
(hand, grip_type, edge_mm) combination, produced by a deliberate testing
protocol (not inferred from WorkSets). Expected to be rare in practice
(mainly run when switching grip/edge) — see CurrentMax for the number
actually used day-to-day. Logging a TrainingSession for a combination with
no prior MaxWeightTest prompts for a test first (or a SessionMaxEstimate as
a per-session stand-in). Never edited in place; a new test simply
supersedes the old one as input to CurrentMax.
_Avoid_: Max weight (as a mutable profile field), 1RM

**Guided max test**:
The "deliberate testing protocol" that produces a MaxWeightTest (issue
#21/#14): a stateless, single-hand routine, run per (hand, grip_type,
edge_mm). The user enters a rough estimated max, then does a warmup of 2
sets x 8 reps, both fixed at 50% of that estimate (never chained off each
other). Every set from warmup set 2 onward is rated for effort
(Effortless/Fairly easy/Moderate/Hard/That's enough); a rating drives the
next suggested weight via a per-unit effort-increment ladder (kg:
+10/+5/+2/+1; lbs: +20/+10/+5/+2.5 — mirroring ADR-0003's native-unit
precedent, never a raw conversion) applied to the just-confirmed actual
weight, never the suggestion shown. A Moderate/Hard rating shows a
plain-text "rest 3-5 min" hint on the following set (no timer). Tapping
"That's enough" writes that final set's actual weight as the hand's
MaxWeightTest; abandoning the routine at any point writes nothing, because
all running state (current actual weight, next suggestion) is threaded
across requests via the page itself and never persisted until that one
terminal action. In the two-hand alternating flow, the passive hand's
running state travels as a single opaque ladder-state token (one hidden
field, encoded/decoded and re-validated only by the guided-max-test
module — never as loose per-field form params). Entirely independent of
SessionMaxEstimate: the up-front estimated max here is a transient,
one-shot seed for this routine only, sharing no storage or code path
with it.
_Avoid_: Max test wizard, 1RM calculator

**CurrentMax**:
For a given (hand, grip_type, edge_mm), the heavier of (a) the most recent
MaxWeightTest, or (b) the heaviest single WorkSet weight logged since that
test — a work set heavier than the last formal test is itself proof the
real max increased, without waiting for a retest. This is the number
actually used for ramp/warmup % suggestions, the %bodyweight-vs-grade
correlation, and any "current max" display.
_Avoid_: Max (bare), 1RM

**SessionMaxEstimate**:
An ephemeral, per-TrainingSession stand-in for CurrentMax, entered by the
user on the warmup page when a (hand, grip_type, edge_mm) combination has
no MaxWeightTest yet. Feeds that session's ramp suggestions and work-set
prefills only. Never a MaxWeightTest, never an input to CurrentMax, and
never feeds the %bodyweight-vs-grade correlation — a combo trained only
under an estimate stays excluded from that analysis exactly like an
untested one. Scoped to one TrainingSession: a new session for a
still-untested combo prompts again from scratch.
_Avoid_: Estimated max (as a stored strength record), target weight

**GripType**:
A named hand position used for a WorkSet or MaxWeightTest (e.g. half_crimp,
open_hand). Stored in a `grip_types` lookup table, seeded with a starter
list, so new grips can be added without a code change/deploy.
_Avoid_: Grip, Hand position

**RPE**:
Rate of perceived exertion for a WorkSet, on a 1.0–10.0 scale in 0.5
increments (matching common autoregulated-training usage, e.g. 7.5). Always
optional/nullable.
_Avoid_: Effort, difficulty rating

**PlateInventory**:
The set of plates (weight_kg + count owned) a user has available, used to
round computed ramp/warmup target weights down to the nearest actually
loadable total. Modeled as a single stack (one loading pin/handle), not
split two-sided like a barbell. New users get a seeded default inventory,
editable at any time.
_Avoid_: Plate rounding config

**HandOrderPreference**:
A per-user setting controlling how a TrainingSession's warmup/ramp and
work-set pages present its two hands. "alternating": both hands shown
together, one row per step/set with L/R columns. "sequential": the full
page flow (warmup then work sets) is completed for one hand, then repeated
for the other.
_Avoid_: Hand order, session order

**UnitPreference**:
A per-user, effectively-fixed choice of kg or lbs made at signup that
determines the *storage* unit for all of that user's weight values
(BodyWeightLog, MaxWeightTest, WorkSet weight, PlateInventory) — not merely
a display conversion. Switching units later isn't supported.
_Avoid_: unit_pref (as a cosmetic display setting), weight unit

**Invite**:
A code/link generated by an existing user that permits creating exactly one
new account. Registration requires one — there is no open self-signup.
_Avoid_: Invite code, referral

**Climb**:
A logged climbing send: date, discipline, grade, style, notes.

**Discipline**:
Whether a Climb is `boulder` or `sport` — determines which grade scale its
`grade` string belongs to (e.g. V-scale/Font for boulder, French/YDS for
sport). Only `boulder` climbs feed the %bodyweight-vs-grade correlation
analysis, matching the scope of the Lattice research it's framed against.

**Style**:
How a Climb was sent — a fixed set of values (`onsight`, `flash`,
`redpoint`, `attempt`), not a lookup table.

**Admin**:
A User with `is_admin = true` (the first registered account, by default).
Can generate Invites and reset other users' passwords — not a general role
system, just those two capabilities.
_Avoid_: Superuser, owner (as a role name)

**TrainingVolume**:
A TrainingSession's total performance for one (hand, grip_type, edge_mm)
combo: Σ(weight × reps) across its WorkSets. The primary signal for
strength trend/plateau analysis — rewards adding weight, reps, or sets
equally.
_Avoid_: Volume (bare), load

**Plateau**:
A sustained lack of TrainingVolume growth across a user's recent
TrainingSessions for a given (hand, grip_type, edge_mm) combo — a signal to
consider changing grip/edge or running a new MaxWeightTest.
_Avoid_: Sticking point, stall

**OvertrainingWarning**:
A dashboard flag for a given (hand, grip_type, edge_mm) when a session's
TrainingVolume spikes well above its recent trailing average *and* the rest
interval before it was shorter than the user's typical recent rest —
requires both signals together, not either alone. A heuristic warning, not
a diagnosed state; exact thresholds are tunable.

**AsymmetryGap**:
The signed percentage difference between left and right hand performance for a
given (grip_type, edge_mm) combination: `(left - right) / max(left, right) * 100.0`.
Computed for both strength (CurrentMax from MaxWeightTests or WorkSets) and
training load (TrainingVolume per TrainingSession). Positive values indicate
left-hand dominance; negative values indicate right-hand dominance.
_Avoid_: Bilateral difference, asymmetry ratio

**AsymmetryWarning**:
A dashboard flag on a bilateral (grip_type, edge_mm) pair when training load
asymmetry drifts significantly from the user's personal baseline (`recent - baseline >= 5.0`
percentage points) or reaches an elevated absolute threshold (`recent >= 15.0%`).
Requires at least 6 non-deload bilateral sessions (3 recent + minimum 3 baseline) so
thin data remains silent. Detects meaningful widening of imbalances without false-alarming
on natural limb dominance (ADR-0010). Narrowing gaps never warn.
_Avoid_: Injury warning, imbalance alarm

**TrainingProtocol**:
The ramp percentages (50/65/80/90% of CurrentMax), base work-set rep count
(the rep target, default 5), and default rest duration applied to a user's
TrainingSessions. Modeled as its own config concept (a global default row,
optionally overridden per user) rather than hardcoded constants. Since Wave 4
the rep target and `default_rest_seconds` are editable per user from the
"Configure training sessions" settings card (a per-user row); the ramp
percentages stay global for now. See ADR-0005 and ADR-0011.
_Avoid_: Settings, config (bare)

**Autoregulation suggestion**:
A transparent, per-hand Tier-1 nudge on the work-set card. When the last two
non-deload sessions for a (hand, grip, edge) both hit the user's target at
RPE ≤ 7 on every working set, it suggests the next step. *What* that step is —
add a set, add weight, or add a rep — is set by the combo's ProgressionPath; the
RPE gate is only the trigger (see ADR-0011 for the trigger, ADR-0012 for the
path). RPE ≥ 9 or a below-target set withholds the suggestion ("hold") — it never
suggests a lower weight and never pre-fills the stepper. A working set with no RPE
makes the session ineligible. Deterministic and rule-based, not AI.
_Avoid_: Coaching, AI suggestion, auto-progression

**ProgressionPath**:
The per-combo scheme deciding what the Autoregulation suggestion advances when the
RPE trigger says you're ready. One of: **Set progression** (fixed weight/reps, add
a set up to a cap), **Weight progression** (fixed sets/reps, add a loadable
increment — the default), or **Double progression** (over a user-set rep range,
default 5–10: build reps to the top, then build weight until reps fall to the
minimum, then reset to a heavier baseline). Chosen per (hand, grip, edge) in the
"Configure training sessions" settings card with a user-level default; never
overridden mid-session, never auto-switched. Config is stored; the current phase
is derived from WorkSet history. See ADR-0012.
_Avoid_: Program, plan, periodization (bare)

**Retest nudge**:
A session-start banner suggesting a fresh guided MaxWeightTest when CurrentMax has
drifted ≥ one loadable increment above the last MaxWeightTest *and* ≥ 8 weeks have
passed since that test. The 8-week floor keeps a retest measuring real training
progress, not day-to-day noise. Suggests only — never auto-adjusts CurrentMax.
See ADR-0011.
_Avoid_: Retest reminder (implies scheduled/time-only)

**Estimate nudge**:
A session-start banner suggesting a guided MaxWeightTest for a combo that has no
MaxWeightTest yet but has accumulated a SessionMaxEstimate across 3 distinct
sessions. See ADR-0011.

**Mean-intensity**:
Per session, the simple mean of each working set's `weight ÷ CurrentMax` (CurrentMax
evaluated as of the session date) for a (hand, grip, edge). Plotted as a second
series on a secondary axis of the per-combo trend chart, beside TrainingVolume, so
intensity progress at trimmed volume doesn't read as a plateau. Sessions with no
CurrentMax (untested/estimate-only) are skipped. See ADR-0011.
_Avoid_: Intensity (bare — ambiguous with RPE)

**BodyWeightLog**:
A dated bodyweight entry. The most recent entry is the user's "current"
bodyweight; the full history is what strength-vs-bodyweight analysis uses,
matched to the closest entry at or before each TrainingSession/test date.
_Avoid_: Bodyweight (as a mutable profile field)

**edge_mm**:
Stores the grip's characteristic dimension in mm; for pinch that's block width, for most other grips it's edge depth. The DB column keeps the name `edge_mm` across all grips for stability, but the UI labels it dynamically based on the selected GripType's `dimension_name`.

**SessionNumber**:
Orders multiple TrainingSessions on the same date (default 1; two-a-days
get 2, 3, …). Identity-bearing: a session's stable key is (user, date,
session_number), which the future offline-sync replay (#20) relies on. A
descriptive `started_at` timestamp exists but is never identity-bearing.
_Avoid_: Session id (ambiguous with the DB primary key)

**Deload**:
A TrainingSession the user marks as a planned light session (`is_deload`).
Deload sessions are excluded from TrainingVolume trend/plateau math so an
intentional easy week doesn't read as a Plateau.
_Avoid_: Rest week, light flag

**PainReport**:
An autosaved per-session annotation — (hand, severity 1–3, optional note),
at most one row per (session, hand). Ground-truth signal being accumulated
for the future finger-injury guardian (#28); no analytics consume it yet.
_Avoid_: Injury (it's a tweak/niggle record, not a diagnosis)

**Voided MaxWeightTest**:
A max test the owner flagged as bad data (`voided_at` set, self-service).
The row is never deleted, but voided tests are excluded from CurrentMax
and every consumer of it; voiding a combination's only test returns that
combination to "needs test/estimate".
_Avoid_: Deleted test

**Export archive**:
The versioned ZIP produced by `GET /profile/export` and consumed by import — a
`manifest.json` (`format_version`, `unit`, `exported_at`) plus one CSV per
exported model. Grips are carried by name (`GripType.csv`), not by raw id, and
weights are stamped in the account's native UnitPreference (see ADR-0003, -0008).
The manifest, not the column-header suffix, is the authority on the archive's
unit.
_Avoid_: Backup (it isn't an off-box/automated backup), CSV dump (it's a
structured, versioned archive, not loose CSVs)

**Account restore**:
Loading an Export archive into an **empty** account (no TrainingSession, Climb,
MaxWeightTest, or BodyWeightLog for that user; seeded plates don't count). Every
row is inserted fresh under the current user — file-supplied ids and `user_id`
are discarded — in one all-or-nothing transaction. There is no merge/append into
a populated account; that's a deliberately deferred, separate feature (ADR-0008).
_Avoid_: Import (as a synonym for merge), Sync (#20 offline sync is unrelated)
