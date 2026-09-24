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
confirmation rather than instantiating silently (issue #51). Since #149
the start page is Today (`/session/new` redirects there) and "start a second
session today" lives in its Change picker.
_Avoid_: Session (ambiguous with the auth/login session), Workout, Training Log

**Session play**:
A training session runs on one page, `/session/play`, full screen with no
tab bar (`docs/adr/0014-session-play-as-server-driven-steps.md`). The
server derives the current **step** purely from persisted state — warmup
ticks recorded, work sets committed against the planned set count, and
whether a rest is pending — and renders it as an htmx fragment (a full page
without htmx, or after a plain form POST). The step names are: **Warmup
rung** (one ramp rung at a time, with tick targets and a "Rung done"
button), **Work set** (the hand cards and steppers, unchanged Set commit —
with its plate-breakdown readout), **Rest** (a ring countdown computed from
the stored `rest_ends_at`, never a decrementing counter — see below), and
**Summary** (issue #147): "Session done." with the date, the duration so
far and the combo; stat tiles for this session's TrainingVolume, sets per
hand and the average of the logged set RPEs; the **Session RPE** chips;
**tweaks** (None / Left / Right, then a severity 1–3 and note — the
existing PainReport, at most one per hand); the session **notes** and the
**Deload** toggle (all of these autosave per interaction — they moved here
from the old "How did it feel?" card on the work-set step, which is gone);
and **Finish**, which stamps `finished_at` once (idempotent) and goes home.
In sequential HandOrderPreference, while the other hand still has sets to
do, "Start {other} hand" is the summary's primary button and Finish the
secondary one. Once `finished_at` is set, the session always resumes on its
(still editable) Summary — even if a set is later deleted — except for an
explicit ⋯ "Add a set" (which shows that one extra work set) and a
sequential other hand that hasn't logged anything yet. The page always
opens on the right step after a pause, reload, or Android killing the app. Replaced the two separate `/session/warmup` and
`/session/worksets` pages, which now redirect to it. The Work set step
also carries a server-rendered **undo-after-delete** banner right after a
`/session/set/delete`: the deleted set's values ride along as query
params on the no-JS redirect (or straight in the htmx fragment) so an
**Undo** button can restore it via the existing `/session/set/restore`
with no server-side undo state of its own — it shows once, on that one
response, never on a later unrelated visit.
_Avoid_: warmup page, worksets page (as separate screens — they're steps of
one page now)

**Session RPE**:
A whole-session effort rating (`session_rpe`, a nullable integer bounded
1–10), asked once on the Summary step as five chips — Easy 3 · Moderate 5
· Hard 7 · Very hard 9 · Max 10 — and autosaved on tap (re-tapping another
chip overwrites it). Distinct from a WorkSet's per-set RPE: the Summary's
"average RPE" tile is the mean of those per-set values, Session RPE is the
user's single rating of the whole session. Exported/imported with the
TrainingSession row (older archives without it still import).
_Avoid_: sRPE (in UI copy), session difficulty, feel

**Session load**:
Session RPE × duration in minutes, where duration runs from `started_at` to
`finished_at` (the Summary's Finish). `started_at` is the first real activity
on the session — the first rung-done, warmup tick, estimate or Set commit — not
the row's creation: a row created early by Go lighter or a tweak logged before
training has no `started_at` until play begins. Derived, never stored
(`analytics.session_load`); `None` whenever Session RPE or either timestamp
is missing, so an unfinished session has no load. Nothing consumes it yet —
it's the standard load signal meant for the OvertrainingWarning and the
injury guardian (#28), per docs/adr/0014.
_Avoid_: Training load (ambiguous with TrainingVolume), tonnage

**Today plan**:
What the Today screen (`/`, issue #149) proposes for today's session, derived
by `backend/today.py` from data already logged — never stored. The combo is the
last-trained (grip_type, edge_mm) unless the user picks another with **Change**;
sets × reps come from the TrainingProtocol and the combo's ProgressionPath (Set
progression's "+1 set" and Double progression's "+1 rep" raise them); each hand's
weight is the Autoregulation suggestion's next rung when it's ready, else the
last session's top weight on that combo, else CurrentMax — with a one-line
reason ("+0.5 kg: last session felt easy (RPE 7)"). **Go lighter** is offered
(never automatic) after a PainReport in the last 7 days, or while the Plateau
or OvertrainingWarning flag is on for the combo: tapping it marks today's
TrainingSession `is_deload` and scales every weight to 85%, rounded *down* to
the Loadable ladder; tapping again restores the plan. Tapping Start accepts the
plan: session play pre-fills set 1 of each hand with exactly these weights and
reps (one derivation, `backend/plan.py`, shared by both screens; carry-down
from the previous set still wins from set 2 on, and the steppers stay
adjustable — ADR-0011 amendment, 2026-09-24). Today's states, in
precedence order: **done** (today's latest session was Finished on its Summary
step, or every planned set of it is committed — shows a recap with Session RPE
once rated, and "Log a climb"), **resume** (today's session has a
warmup tick, estimate or work set but isn't done — "Resume · set N of M"),
**no data yet** (nothing tested or trained — prompts the guided max test),
**rest day** (see Rest-day suggestion), and **plan**. An empty session row (from
Go lighter, or a tweak logged before training) doesn't count as started.
_Avoid_: Program, workout of the day, prescription

**Rest-day suggestion**:
Today's headline becomes a rest-day message when the user trained (logged work
sets) on each of the two days before today, or while the OvertrainingWarning is
on for the planned combo. Advisory only: Start stays available as a secondary
"Train anyway" button — it never blocks a session.
_Avoid_: Forced rest, lockout

**＋ Log sheet**:
The bottom sheet behind the tab bar's centre ＋ (issue #149): quick capture of a
Climb, a BodyWeightLog entry, or a PainReport ("Tweak", on the day's session,
created under the usual start_or_get_session and past-date rules). Opened in
place by htmx without a history entry; `/?log=climb|bodyweight|tweak` opens it
server-side. Replaced the standalone climb page (`/climbs` now redirects there);
the climb list lives on the Progress Timeline.

**Progress**:
The second tab (`/progress`, issue #150), answering "am I getting stronger, and
does it show in my climbing?" in three layers: **Story sentences** on top, then
one headline chart, then **Go deeper** rows that open detail pages. The chart is
CurrentMax as a share of bodyweight, per hand, as of each date the chosen
(grip_type, edge_mm) was trained or tested (`CurrentMax(as_of=d) /
bodyweight(as_of=d)`, reusing the CurrentMax rule and the bodyweight time series;
dates with no CurrentMax or no bodyweight are skipped), drawn as step lines —
Left solid accent, Right dotted chalk — with parsed boulder sends as
grade-coloured dots on a second, grade axis. A combo picker appears once more
than one (grip, edge) has data (default: last trained) and a range picker offers
6W / 3M / All; both are plain query params that htmx swaps in place. Go deeper
holds Training volume, Left/right balance, Strength vs grade (moved unchanged
from the old Trends page), **Maxes** (current maxes, test history with void, the
manual and guided max-test forms — from the old Max tests page) and the
**Timeline**. Raw data lists sit behind collapsed "Show data" disclosures.
Absorbed Trends, History and Max tests: `/dashboard`, `/history` and
`GET /max-tests` 303 into it.
_Avoid_: Trends, dashboard, stats (for the page)

**Story sentence**:
One line of Progress's headline layer: a bold claim plus muted advice, written
from a fixed template over an *existing* analytics signal and shown only when
that signal passes its own threshold — never a new statistic
(`backend/progress.py` `story_sentences`). At most three, in priority order:
CurrentMax %BW change over the range per hand (only if it moved by a whole
percent), the Plateau flag, the OvertrainingWarning, the AsymmetryWarning, and
the strength–grade correlation's ρ in words (only past its n ≥ 8 floor). With a
slot left, one "what's missing" line names the thinnest gap (no max test, no
bodyweight, or how many more boulder sends the correlation needs — never a
negative count).
_Avoid_: Insight, headline stat, AI summary

**Timeline**:
Progress's "All sessions & climbs" detail page (`/progress/timeline`, replacing
History): every TrainingSession and Climb, newest first, grouped by Monday-start
week, with a "Climbs only" filter (`?show=climbs`). A session row shows its first
combo (+N when it trained more), top set, total volume, Session RPE and a Deload
tag, and opens that session in Session play (its date, combo and
session_number — a finished session lands on its Summary); its raw sets stay
behind "Show sets". A climb row shows a grade dot and the style.
_Avoid_: History, log, feed

**Settings**:
The fourth tab (`/settings`, issue #151), replacing the old Profile and Plates
pages: grouped glass list rows — **You** (name, bodyweight, and the account
email in the server build), **Training** (HandOrderPreference, the
TrainingProtocol's rep target and rest, ProgressionPath default and
overrides), **Equipment** (the PlateInventory rack; UnitPreference shown
read-only, "kg · fixed"), **Rest alerts** (Rest sound), **Your data** (Export
archive download, Account restore, About these numbers) and, in the server
build only and for an Admin, **Admin** (invites, grip types, password reset —
hidden in the WebView build, ADR-0013). Each row opens a small detail page.
Changes **autosave**: forms post on change and answer with a "Saved" toast
(htmx) or a 303 back to their page with `?saved=` (no JS). `/profile` and
`/plates` redirect here; their POST endpoints keep their URLs.
_Avoid_: Profile, preferences, account page

**About these numbers**:
Settings' static page (`/settings/about`) explaining TrainingVolume,
Mean-intensity, CurrentMax as % of bodyweight, RPE and Session RPE, Session
load, the AsymmetryGap and the strength–grade correlation in plain language.
The technical terms (TrainingVolume, CurrentMax, Spearman ρ) live here; the
Progress pages use plain labels and link to the matching section instead.
_Avoid_: Methodology, glossary (this file is the glossary)

**rest_ends_at**:
A nullable `datetime` on `TrainingSession`: when set, the play step is
**Rest**, and the ring countdown is always computed from this stored end
time (`now` vs. `rest_ends_at`), never from a client-side decrementing
counter — so a reload or the app being killed and reopened resumes at the
right remaining time instead of restarting the clock. Set to
`now + TrainingProtocol.default_rest_seconds` by a normal (non-final,
non-edit) Set commit; **+30 s** bumps it by exactly 30 seconds; **Skip
rest** and **Start set N** both clear it. Once it's in the past, the rest
step shows "Pull" / **Start set N** until the user acts — it is never
silently skipped.
_Avoid_: rest timer state, countdown seconds (nothing is stored as a
plain remaining-seconds counter)

**Rest bridge**:
The small feature-detected native interface the Android shell injects as
`window.GripTrackNative` (`docs/adr/0015-native-rest-bridge.md`, #148):
keep the screen on during **Session play**, a lock-screen countdown
notification to `rest_ends_at`, and an exact alarm that vibrates at the rest
end ("Pull. Set N is ready"). The web ring stays the source of truth for
what the app shows; the alarm is the source of truth for the alert. Without
the bridge (a plain browser) the page falls back to the Screen Wake Lock API
and has no alert.
_Avoid_: rest service, native timer (there's no foreground service and no
second countdown to keep in sync)

**Rest sound**:
A per-user boolean (`User.rest_sound`, off by default): when on, the Rest
bridge's rest-over alert also plays the default notification sound on top
of the vibration. Off by default because shared gyms are quiet places.
Toggled in Settings → Rest alerts (`POST /settings/rest-sound`, #151); the
rest step only hands the stored flag to the bridge's `startRest`.
_Avoid_: alarm sound, rest beep

**WorkSet**:
One set of the tracked work-set portion of a TrainingSession (hand,
grip_type, edge_mm, weight_kg, reps, set_number, rpe). Warmup/ramp sets are
never persisted as WorkSets — they're computed and shown, not logged.
_Avoid_: Set, Rep set

**Set commit**:
The single gesture that writes a set — the "Set done" button on Session
play's Work set step. Writes both hands' WorkSets for one set_number in one atomic
request (`POST /session/set`), or one hand's under a sequential
HandOrderPreference. Until it fires, the stepper values on screen are
unsaved client state, so the set does not exist. Replaced the old
per-cell autosave table, where each field saved on its own; see
`docs/adr/0007-set-commit-over-per-cell-autosave.md`.
_Avoid_: Save, submit (the screen has no form-submit model)

**Edit mode**:
The Work set step's correction path. Tapping a row in the COMPLETED list
reopens that set's values in the hand cards (the row is highlighted) and
the commit button becomes "Save" alongside a Cancel. Saving takes the same
Set commit path — without starting a Rest — and returns to the set the
user was on. Exists so there is exactly one editing surface for a
WorkSet rather than a second, smaller one embedded in the completed list.
_Avoid_: Inline edit, edit form

**Loadable ladder**:
Every total weight a user's PlateInventory can actually make on the single
pin, in ascending order — the full achievable set that
`round_down_to_loadable` already computes internally and discards above
its target. The Work set step's weight steppers walk this ladder one rung
per tap, so every reachable value is physically loadable. Embedded in the
page as JSON so taps stay instant and work offline. A starting value that
is off-ladder (a CurrentMax straight from a MaxWeightTest, or older
free-entry history) snaps to the next rung in the direction of travel;
both ends clamp. Bounded like every other numeric input, since the
subset-sum behind it is the DoS-sensitive path.
_Avoid_: Increment, step size (it is not a fixed step)

**Plate breakdown**:
One concrete combination of plates (`backend.plates.plate_breakdown`,
largest first) that makes an exactly-loadable weight — the "Pin + 20 +
1.25" readout under a rung's or work set's weight. Reuses the loadable
ladder's own bounded subset-sum search rather than a second one; shows
nothing (not a wrong or partial breakdown) for a weight that isn't itself
on the ladder, e.g. an off-ladder `CurrentMax` or a free-entry value.

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
user on Session play's first warmup step when a (hand, grip_type, edge_mm) combination has
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
split two-sided like a barbell; weights are the plates on the pin — the
pin itself is never counted. New users get a seeded default inventory,
editable at any time as tap-to-count plate circles (first run and Settings →
Plates, #151): each tap adds one, wrapping to 0 (removing the plate) past
10; the unit's starter sizes stay on the rack at ×0.
_Avoid_: Plate rounding config

**HandOrderPreference**:
A per-user setting (Settings → Training) controlling how Session play
presents a TrainingSession's two hands. "alternating": both hands shown
together on every warmup rung and work set. "sequential": the whole flow
(warmup then work sets) is completed for one hand, then repeated for the
other — the Summary offers "Start {other} hand".
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
the rep target and `default_rest_seconds` are editable per user in
Settings → Training (a per-user row); the ramp
percentages stay global for now. See ADR-0005 and ADR-0011.
_Avoid_: Settings, config (bare)

**Autoregulation suggestion**:
A transparent, per-hand Tier-1 nudge on the work-set card. When the last two
non-deload sessions for a (hand, grip, edge) both hit the user's target at
RPE ≤ 7 on every working set, it suggests the next step. *What* that step is —
add a set, add weight, or add a rep — is set by the combo's ProgressionPath; the
RPE gate is only the trigger (see ADR-0011 for the trigger, ADR-0012 for the
path). RPE ≥ 9 or a below-target set withholds the suggestion ("hold") — it never
suggests a lower weight. The inline hint itself is text only; the suggested
weight reaches the stepper only through the Today plan, as set 1's prefill once
the user taps Start (ADR-0011 amendment). A working set with no RPE
makes the session ineligible. Deterministic and rule-based, not AI.
_Avoid_: Coaching, AI suggestion, auto-progression

**ProgressionPath**:
The per-combo scheme deciding what the Autoregulation suggestion advances when the
RPE trigger says you're ready. One of: **Set progression** (fixed weight/reps, add
a set up to a cap), **Weight progression** (fixed sets/reps, add a loadable
increment — the default), or **Double progression** (over a user-set rep range,
default 5–10: build reps to the top, then build weight until reps fall to the
minimum, then reset to a heavier baseline). Chosen in Settings → Progression as
a user-level default plus optional per-(grip, edge) overrides; never
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
The versioned ZIP produced by `GET /profile/export` (Settings → Export backup)
and consumed by import (Settings → Restore from backup) — a
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
