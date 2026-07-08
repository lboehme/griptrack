# GripTrack — Product Overview (non-technical)

*Snapshot of everything the app does as of 2026-07-08. Written as grill
input for a design/architecture review; the companion piece is
`docs/technical-guide.md`.*

## What GripTrack is

GripTrack is a mobile-first web app for climbers who train finger strength
with block pulls / no-hangs (lifting a weighted pin off the floor with one
hand on a gripping block, rather than hanging from a board). It does three
things:

1. **Logs training** — max-strength tests, structured training sessions,
   and climbing sends.
2. **Guides training** — it computes the warmup ramp and suggested working
   weights for each session from the user's tested maximum, rounded to
   weights the user's own plates can actually make.
3. **Analyses training** — trend charts, plateau detection, an
   overtraining warning, and a correlation between finger strength (as %
   of bodyweight) and boulder grade.

It runs in the phone browser and can be installed to the home screen like
an app. It is live at `https://griptrack.duckdns.org`, used by a small,
invited group of people.

## The core idea: everything is per grip, per edge, per hand

Finger strength isn't one number. Pulling on a 20 mm edge in half crimp is
a different capacity than a 10 mm edge in open hand, and the left and
right hand differ too. GripTrack therefore keys almost everything on a
**combination** of *hand + grip type + edge size (mm)*. Max tests, session
suggestions, trend charts, and plateau flags all exist once per
combination, never as a single blended "finger strength" score.

Two derived numbers drive the app (neither is ever entered directly):

- **CurrentMax** — for a combination, the heavier of (a) the most recent
  formal max test and (b) the heaviest single work set logged since that
  test. Rationale: if you trained heavier than your last test, that *is*
  evidence your max went up — no retest needed. A newer test always
  supersedes older data, even if it's lower (a deliberate reset, e.g.
  after injury). All weight suggestions and the strength-vs-grade analysis
  use CurrentMax.
- **TrainingVolume** — one session's total for a combination:
  Σ (weight × reps) across its work sets. This is the trend/plateau
  signal, and it rewards adding weight, reps, or sets equally.

## Accounts and access

- **Invite-only registration.** There is no open signup. An existing user
  generates a one-time invite code and shares it; the code permits exactly
  one new account. There is no email infrastructure at all — no
  verification mails, no self-service password reset.
- **First account = admin.** On a fresh install, the first registration is
  gated by a server-side bootstrap token and becomes the admin. Admin
  means exactly two extra abilities: generating invites and manually
  resetting another user's forgotten password. It is not a general role
  system.
- **Login/logout** with email + password. Repeated failed logins from one
  address are temporarily blocked.
- **Optional display name.** Users can set a name for the greeting;
  otherwise the app greets them by the part of their email before the `@`.

## Profile and setup

- **Unit preference (kg or lbs)** — chosen at signup and then fixed. This
  is not a display toggle: every weight the user ever enters is stored in
  their unit, because plates are physically kg- or lb-denominated objects
  and converting would produce unloadable numbers.
- **Hand order preference** — how two-handed pages are laid out.
  *Alternating*: both hands side by side, one row per step with L/R
  columns. *Sequential*: complete the whole flow for one hand, then repeat
  for the other.
- **Bodyweight log** — bodyweight is a dated series of entries, not a
  profile field you overwrite. The analysis matches each climb/session to
  the bodyweight entry closest before it, so historic data stays honest.
- **Plate inventory** — the set of plates the user owns (denomination +
  count), modeled as a single stack on one loading pin. New users get a
  sensible starter set (different defaults for kg and lbs users) and can
  edit it anytime. Every suggested weight in the app is rounded **down**
  to the nearest total the user's actual plates can make.

## Max testing

A **max weight test** is a dated record of the heaviest pull for one
combination. Tests are append-only — never edited, a new test simply
supersedes the old. In practice they're rare (mainly when switching grip
or edge). Two ways to create one:

- **Manual entry** — pick hand, grip type, edge, date, weight. New grip
  types can be added from this page without a code change (the starter
  list: half crimp, full crimp, open hand, three finger drag, pinch).
- **Guided max test** — a step-by-step routine for one combination. The
  user enters a rough estimated max; the app prescribes a warmup (2 sets
  of 8 reps at 50% of that estimate), then single attempts. After each
  attempt the user rates the effort (*Effortless / Fairly easy / Moderate
  / Hard / That's enough*), and the rating determines the suggested jump
  for the next attempt (e.g. in kg: +10 / +5 / +2 / +1). "Moderate" or
  "Hard" shows a "rest 3–5 min" hint before the next attempt. Tapping
  "That's enough" records that final weight as the max test. Abandoning
  the routine mid-way records **nothing** — there is no half-finished
  test state. A two-hand variant alternates attempts between hands within
  one flow.

## Logging a training session

Starting a session means picking hand(s), grip type, and edge — defaulting
to whatever was last used. A session is **not** a multi-page wizard with a
submit button; it is two consolidated pages where **every interaction
saves immediately**. A session therefore exists in the database from the
first tap and can legitimately sit half-filled — there is nothing to lose
by getting interrupted at the gym.

1. **Warmup/ramp page** — a checklist of ramp steps computed from
   CurrentMax and the training protocol (50 / 65 / 80 / 90% of max, each
   plate-rounded). The user ticks steps off as they do them; a mis-tap can
   be unticked. Warmup steps are shown and checked, but never stored as
   training data — only work sets count.
2. **Work-sets page** — an editable table (default 3 rows, "add another
   set" for more, extra empty rows dismissable) with weight, reps, and an
   optional RPE (perceived effort, 1–10 in 0.5 steps) per set. Weights are
   prefilled from CurrentMax and the protocol's default rep count (5).
   Sets can be edited or deleted afterwards.

**Untested combination?** If the chosen combination has no max test yet,
the warmup page asks inline for either a proper max test or a one-off
**session estimate** — a stand-in max for *this session only*. It feeds
that session's suggestions and nothing else: it is never stored as a
strength record, never feeds analysis, and a later session for the same
untested combination asks again.

**Training protocol.** The ramp percentages and default rep/set counts are
a single shared configuration (not per-user yet, but deliberately modeled
so per-user overrides can be added later without rework).

## Logging climbs

A climb entry is: date, discipline (**boulder** or **sport** — which
determines the grade scale), grade (free text, e.g. `V5` or `7A`), style
(**onsight / flash / redpoint / attempt**), and notes.

## History

One page listing all past training sessions (with their work sets) and all
logged climbs, newest first, strictly scoped to the logged-in user — no
user can ever see another's data.

## Analytics dashboard

For every combination the user has trained or tested:

- **Volume trend chart** — TrainingVolume per session over time, rendered
  by the server as a clean SVG chart (light- and dark-theme variants).
- **Plateau flag** — raised when the last 4 sessions never exceeded the
  best volume of the sessions before them: a nudge to change grip/edge or
  retest.
- **Overtraining warning** — raised only when *both* of these hold for
  the latest session: its volume spiked ≥ 25% above the trailing average
  *and* it followed a shorter-than-typical rest gap. Either signal alone
  never fires. Explicitly a heuristic guardrail, not a diagnosis.
- **Strength-vs-grade correlation** — plots best pull strength as % of
  bodyweight against boulder grade at each send date, and reports the
  correlation once there are at least 3 varied points. Boulder climbs
  only (matching the scope of the published Lattice research this is
  framed against — framed against, not reproducing). Grades in V-scale
  or Fontainebleau are understood (Font is converted to V internally);
  anything else stays logged but is excluded from this analysis. Sends
  from combinations that were never formally tested are excluded too —
  session estimates never leak into analysis.

## App-like behavior (PWA)

GripTrack installs to the phone home screen with its own icon and opens
full-screen like a native app. The visual shell loads instantly from cache
on repeat visits, and when there is no connectivity a friendly offline
page appears instead of a browser error. **Logging while offline is not
supported yet** (that's tracked as future work); user pages always come
live from the server.

## What the app deliberately does not do (yet)

Recorded future work, not accidental gaps: progression-path suggestions
(users add weight/reps by their own judgment), per-user protocol
overrides, open self-signup + email flows, offline logging with sync, a
between-set rest timer, a unified grade-conversion matrix beyond
Font→V, left/right asymmetry analytics, and — building on that — a
per-grip finger-injury risk guardian. An admin protocol-tuning dashboard
and system health metrics are also on the list.
