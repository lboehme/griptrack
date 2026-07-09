# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Agent skills

### Issue tracker

Issues and PRDs live as GitHub issues at `lboehme/griptrack` (private repo). External PRs are not a triage surface. See `docs/agents/issue-tracker.md`.

### Triage labels

Standard five-role vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`), label strings unchanged from the skill defaults — not yet created in the GitHub repo. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## Project context

GripTrack is a mobile-first web app for logging block-pull / no-hang
finger-strength training and climbing sends, with data-science analysis
(strength trend, plateau detection, correlation between block-pull strength
and climbing grade).

This app is being **built entirely by Claude Code** — the user is not
writing code themselves. `griptrack_projektplan.md` (German) is the
*original* learning-project conception, kept for historical domain context
only; where it disagrees with this file or with `CONTEXT.md`, this file and
`CONTEXT.md` win. The architecture and domain model below were worked out
through an explicit design-interview session (the `grilling` +
`domain-modeling` skills), not inherited as-is from that original doc.

**Source of truth for terminology and decisions:**
- `CONTEXT.md` — the project glossary (canonical terms, what to avoid). Keep
  it current as the domain model evolves; this is an active discipline, not
  a one-time snapshot.
- `docs/adr/` — recorded architectural decisions (5 so far). Read these
  before revisiting any of the choices below; each explains a real
  trade-off that was deliberately made.

**Current state (2026-07-09):** the full PRD (issue #1) plus Waves 0–2 of
the post-review roadmap are implemented and deployed to Fly — auth (with
session revocation), profile, plates, max tests (guided routine, voidable),
session logging (multi-session days, notes/deload/pain reports), boulder
climb logging with loud grade feedback, history, CSV export, PWA
(manifest + service worker with content-hash cache version), and the
analytics dashboard (deload-aware volume trend, plateau, overtraining
warning, Spearman %BW-vs-grade correlation with an n≥8 floor) — 173 tests
at the HTTP seam plus ruff/mypy/pip-audit gates. Remaining open work:
Asymmetry Analytics (#45–#48, next up), the Wave 4 retention PRD (#59,
needs its own grill), and the deferred #20/#28. Work test-first (see the
`tdd` skill) and keep migrations in lockstep with model changes.

## Environment & running

Local dev uses a conda env named `griptrack`
(`/Users/lukas/opt/miniconda3/envs/griptrack`). Runtime deps are now pinned in
`requirements.txt` (test extras in `requirements-dev.txt`) — keep those in
lockstep with the conda env when adding a package. `matplotlib`/`pandas` power
the analytics charts and are installed.

Run the API from the repository root (so `backend` resolves as a namespace
package):

```bash
conda run -n griptrack fastapi dev backend/main.py
```

Run tests with `scripts/test` (wraps the conda env; pass pytest args through).
The full dev loop lives in `scripts/`: `scripts/check-migrations` (the two CI
migration gates, runnable locally), `scripts/new-migration "msg"` (autogenerate
a revision against a temp DB at head — never hand-write revision files),
`scripts/lint` (ruff + mypy + pip-audit; mypy has a pyproject override list
for modules that build SQLModel query expressions — extend the list, don't
re-broaden the disabled codes), and `scripts/deploy` (fly deploy + health
check + migration-log verification). CI calls the same `scripts/test` /
`scripts/lint` / `scripts/check-migrations`, so local and CI behavior can't
drift. All tests sit at the HTTP seam.

## Deployment & security

Deployment is containerized and host-agnostic — see `docs/deployment.md` for
the full guide and `Dockerfile` / `docker-entrypoint.sh` / `.env.example`.
Config is via env vars: `GRIPTRACK_ENV=production` (enables Secure cookies +
fail-fast on a missing secret), `GRIPTRACK_SESSION_SECRET` (required in prod),
`GRIPTRACK_DATABASE_URL` (point at a persistent volume), and
`GRIPTRACK_BOOTSTRAP_TOKEN` (gates the first-admin registration).

Security is enforced in code and covered by `tests/test_security.py`: bcrypt
hashing with 8–72-char passwords, per-IP login rate limiting with
timing-equalized auth, `SameSite=Lax` + Origin-check CSRF defense, a security-
header middleware (CSP/XFO/nosniff/Referrer-Policy), and upper bounds on every
numeric input (the plate subset-sum is the DoS-sensitive path). Numeric input
limits live in `backend/limits.py`. When adding a route that takes numbers or
user text, bound it and add a security test.

## Architecture

### Module design

Backend code is organized as a small number of deep modules (see the
`codebase-design` skill for this vocabulary), not fat routers:

- **`backend.auth`** — register/authenticate/session/invite/admin-reset
  logic; hides password hashing and session-cookie handling.
- **`backend.plates`** — one function,
  `round_down_to_loadable(target_weight, inventory) -> weight`; hides the
  single-stack plate-matching search.
- **`backend.training_log`** — the deepest module: `compute_current_max`,
  `compute_ramp_plan`, `start_or_get_session`, `record_warmup_step`,
  `record_work_set`, `record_max_weight_test`. Hides the `CurrentMax`
  rolling-max rule, `TrainingProtocol` lookup, calls into `backend.plates`,
  and autosave persistence. Most of Phase 3/4's real complexity lives here.
- **`backend.analytics`** — `training_volume_trend`, `plateau_flag`,
  `overtraining_warning`, `strength_grade_correlation`; hides the
  `TrainingVolume` formula, thresholds, and boulder-only filtering.
- **`backend.routers.*`** — deliberately shallow HTTP adapters: parse
  request → call into one of the modules above → render template/JSON.
  Depth belongs in the modules, not the routers.
- **`backend.models`** — SQLModel schema; a shared type layer, not a "deep
  module" in this vocabulary.

Per the testing decision below, tests only cross the external HTTP seam
(via `TestClient`) — these modules have potential internal seams but aren't
unit-tested in isolation for now.

- **Backend:** FastAPI.
- **Models/ORM:** SQLModel (SQLAlchemy + Pydantic combined) — one model
  definition serves as both DB table and API schema.
- **Migrations:** Alembic from the start.
- **Database:** SQLite. Weight values are stored in each user's
  `UnitPreference` **natively** (kg or lbs, chosen at signup, not
  switchable later) rather than normalized to a canonical unit — see
  `docs/adr/0003-native-unit-storage.md`. This matters because plates are
  physically fixed kg- or lb-denominated objects; canonical-kg storage would
  produce non-round, unloadable numbers for lb-plate users.
- **Auth:** Invite-only registration, no open self-signup and no email
  infrastructure (no verification emails, no email-based password reset) —
  see `docs/adr/0004-invite-only-registration.md`. Password hashing via the
  `bcrypt` package directly (not passlib — passlib is unmaintained and
  incompatible with bcrypt ≥ 4.1); server-side signed session cookie
  (Starlette `SessionMiddleware`); a `current_user` dependency gates
  per-user data. A simple `is_admin` flag (first registered user, by
  default) grants two capabilities only: generating invites, and manually
  resetting another user's forgotten password — not a general role system.
- **Frontend:** FastAPI + Jinja2 templates + htmx, vanilla JS only where
  htmx can't reach. No build step, no React/Vue, no PWA/offline support (for
  now). Logging a `TrainingSession` is **not** a page-per-step wizard —
  it's two consolidated pages: a warmup/ramp checklist and a work-sets
  table, each laid out with one row per step/set and **L/R columns** so
  both hands appear together (see `HandOrderPreference` in `CONTEXT.md` for
  how "alternating" vs "sequential" changes this layout). Every interaction
  (checking a warmup step, editing a work-set row) **autosaves immediately**
  — there is no final "submit" step, so a `TrainingSession` can exist, and
  often briefly does, in a partially-filled state.
- **Analytics charts:** server-rendered images (matplotlib/plotly → SVG/PNG,
  embedded via `<img>`), not a client-side JS charting library.
- **Deployment:** local only for now
  (`conda run -n griptrack fastapi dev backend/main.py`, tested on a phone
  via the machine's LAN IP). Revisit hosting once the MVP is proven useful.
- **Testing:** `pytest` + FastAPI `TestClient` against an isolated SQLite DB
  per test run. Treated as core scope (Phase 4), not optional polish.

## Domain model

Full canonical definitions live in `CONTEXT.md` — this is just the table
shape. Key concepts to understand before touching any of this: `CurrentMax`
(the number ramp/warmup suggestions and the strength-correlation analysis
actually use — day to day it's usually *not* the raw `MaxWeightTest`, see
below) and `TrainingVolume` (the primary trend/plateau signal, not
`MaxWeightTest`).

- **users**: id, email, hashed_password, is_admin, unit_pref (kg/lbs, fixed
  at signup), hand_order_pref (alternating/sequential), name (optional
  display name), session_version (bumped on password reset — revokes all
  of that user's session cookies), created_at
- **invites**: id, code, created_by_user_id (FK), used_by_user_id (FK,
  nullable), created_at, used_at (nullable)
- **body_weight_logs**: id, user_id (FK), date, weight — a time series, not
  a mutable profile field (`docs/adr/0001-...md`)
- **grip_types**: id, name, dimension_name ("edge depth" / "block width" —
  labels what `edge_mm` means for that grip, see CONTEXT.md) — a lookup
  table (extensible without a deploy), seeded with a starter list
  (half_crimp, full_crimp, open_hand, three_finger_drag, pinch)
- **max_weight_tests**: id, user_id (FK), hand, grip_type_id (FK), edge_mm,
  date, weight, voided_at (nullable — self-service void; voided tests are
  excluded from CurrentMax and all consumers, row never deleted) — dated,
  append-only, scoped per (hand, grip_type, edge_mm), not just per hand
  (`docs/adr/0001-...md`). Expected to be logged rarely in practice.
- **plate_inventory_items**: id, user_id (FK), plate_weight, count — a
  single stack (one loading pin/handle, not split like a barbell); new
  users get a seeded default, editable anytime (`docs/adr/0002-...md`)
- **training_sessions**: id, user_id (FK), date, session_number (unique
  (user, date, session_number) — identity-bearing key for two-a-days and
  offline-sync replay), started_at (descriptive only), notes, is_deload
  (plateau/trend math skips deloads), created_at
- **pain_reports**: id, training_session_id (FK), hand, severity (1–3),
  note — at most one row per (session, hand), autosaving; ground truth
  being accumulated for the injury guardian (#28)
- **work_sets**: id, training_session_id (FK), hand, grip_type_id (FK),
  edge_mm, weight, reps, set_number, rpe (1.0–10.0, 0.5 increments, nullable)
- **climbs**: id, user_id (FK), date, discipline (form is boulder-only since #55; old sport rows still render in history), grade,
  style (onsight/flash/redpoint/attempt), notes
- **training_protocols**: id, ramp_percentages (50/65/80/90 default),
  base_work_set_reps (5 default), user_id (FK, nullable — null means "global
  default"). Single global row in use today; modeled this way so per-user
  overrides are additive later, not a rework (`docs/adr/0005-...md`)

Derived/computed concepts (not stored, see `CONTEXT.md` for full
definitions): `CurrentMax`, `TrainingVolume`, `Plateau`, `OvertrainingWarning`.

Progression paths (set-/weight-/advanced-progression from the original
plan) remain explicitly deferred — users just choose to add weight/reps
themselves. This isn't a complexity call like the others below; it's a
shape call: progression logic is a policy layer reading already-logged
`WorkSet` history, not infrastructure other things depend on, so it can be
layered on later without reshaping today's schema.

## Roadmap

Build in this order; each phase should be working and (from Phase 4 onward)
tested before starting the next.

1. **Scaffolding** — `backend/` layout (`main.py`, `db.py`, `models.py`,
   `auth.py`, `routers/`, `templates/`, `static/`, `analytics.py`), Alembic
   init, install the Phase-0 packages listed above, health-check endpoint.
2. **Data model & migrations** — SQLModel models for all tables above; first
   Alembic migration; seed migration/script for default `grip_types` and a
   new user's default `plate_inventory_items`.
3. **Auth** — invite-only registration (requires a valid, unused `Invite`
   code), login/logout, password hashing, signed session cookie,
   `current_user` dependency, first-ever registered user becomes admin,
   admin-only invite-generation action, admin-only manual password reset
   action. Minimal login/register templates.
4. **Core logging MVP**:
   - Profile setup: unit_pref (fixed at signup), hand_order_pref,
     `plate_inventory_items` (seeded default, editable)
   - `MaxWeightTest` flow: required before the first `TrainingSession` for
     any new (hand, grip_type, edge_mm) combination
   - `TrainingSession` flow: pick hand(s)/grip_type/edge_mm (default to last
     used); warmup/ramp page (computed from `CurrentMax` + `TrainingProtocol`,
     plate-rounded via `PlateInventory`, checklist with L/R columns);
     work-sets page (editable table, "add another set"); both pages
     autosave per interaction, laid out per `hand_order_pref`
   - Climb logging: date, discipline, grade, style, notes
   - History view scoped to the logged-in user
   - Mobile-first CSS, large touch targets. First end-to-end-usable
     milestone — test on a phone via LAN IP.
5. **Tests for phases 2–4** — auth flow, invite redemption, CRUD +
   validation, per-user data-isolation tests (user A must never see user
   B's data), `CurrentMax` computation edge cases.
6. **Analytics** — `TrainingVolume`-based trend per (user, hand, grip_type,
   edge_mm), `Plateau` heuristic, %bodyweight-vs-boulder-grade correlation
   using `CurrentMax` (boulder `Climb`s only, framed against Lattice's
   published methodology per the original plan's positioning notes, not
   reproducing it), `OvertrainingWarning` heuristic, a dashboard page with
   server-rendered charts; tests against fixture data.
7. Deployed to fly.io


Above roadmap is complete, further roadmap here:

## Roadmap (open)

Re-planned 2026-07-09 from `docs/griptrack-full-review.md` (full critical
review) — see `docs/adr/0006-personal-instrument-scope.md` for the framing
decision: GripTrack stays a personal instrument (owner + invited friends),
open-sourcing is the candidate growth path, the public-launch track is
dropped. Waves in order; GitHub issues are the source of truth for status.

- **Wave 0 — hardening PR (shipped 2026-07-09, #50/PR #62):** SQLite WAL mode + `busy_timeout`; ruff + mypy +
  pip-audit in CI; derive the service worker's `CACHE_VERSION` from a
  content hash (kills the manual-bump rule).
- **Wave 1 — data-model corrections (shipped 2026-07-09, #51–#55 / PRs #63, #65, #66, #67, #61 + cleanup #71):**
  1. `session_number` for two-a-day sessions + client-local date default +
     past-date warning banner + explicit (not implicit) past-session creation
  2. Pinch dimension semantics: `dimension_name` on `grip_types` ("edge
     depth" / "block width"); the `edge_mm` column keeps its name — glossary
     note in `CONTEXT.md`
  3. Expose session `notes` + `is_deload` flag (plateau logic skips deloads)
     + minimal pain table `(session_id, hand, severity 1–3, note)`, all
     autosaving
  4. Self-service void-a-test flag; voided tests excluded from `CurrentMax`
  5. Climb form boulder-only (UI-only; schema and history untouched) + loud
     "grade not recognized" feedback instead of silent analytics exclusion
- **Wave 2 — correctness/trust batch (shipped 2026-07-09, #56–#58 / PRs #68, #69, #70):** session revocation (per-user
  session-generation counter; admin password reset invalidates sessions) +
  rate-limit `/register`; Spearman + n≥8 floor for the strength–grade
  correlation; CSV export.
- **Wave 3 — Asymmetry Analytics** (PRD #45, slices #46–#48, ready-for-agent). **← next up.**
- **Wave 4 — retention wave** (one feature surface, needs its own mini-grill
  first): RPE-driven Tier-1 deterministic autoregulation (RPE ≤ 7 twice →
  suggest smallest loadable increment; RPE ≥ 9 / missed reps → hold or step
  down); retest nudge when work-set history implies `CurrentMax` drift;
  "estimated this combo 3× → guided test?" nudge; mean-intensity series
  (weight ÷ CurrentMax-as-of-date) beside tonnage on the trend chart; RPE
  stepper input; in-between-set rest timer (htmx OOB countdown, stored rest
  durations, wake lock, audio/notification strategy).
- **Owner-gated, parallel:** Oracle switch when the account unblocks —
  Litestream enable + restore drill is step one (if the ticket is still
  stuck after ~a week, revisit decoupling backups to R2/B2); PWA phone test
  with an accessibility mini-pass (chart ARIA titles, non-color-only
  warning states, contrast, 44px targets); error-tracking decision
  post-Oracle (Sentry vs self-hosted vs structured logs).
- **Deferred with named triggers:** CSP nonces, admin audit table, first-run
  onboarding, chart-render caching → open-sourcing or audience growth;
  Playwright smoke tests → starting #20; cross-combination aggregate load
  (needs read-time unit canonicalization, the ADR-0003 IOU) and pain-data
  consumption → injury guardian (#28); offline WorkSet sync (#20) → its own
  design grill, someday; stored canonical grades / conversion matrix → if a
  grade matrix ever becomes real (Font + V both already parse); per-user
  `TrainingProtocol` overrides and progression-path logic → after Wave 4
  proves the nudge machinery.
- Finger-injury risk guardian (GitHub issue #28) — build *after* Asymmetry
    Analytics and after Wave 1 pain/deload logging has accumulated real
    data; the existing `OvertrainingWarning` is a crude single-grip
    prototype of it. Needs its own grill + real-data threshold calibration.
- **Dropped (2026-07-09):** Tindeq/force-gauge integration (no owner
  interest yet), sport-climb analytics (climb logging is boulder-only for
  now), V-grade suffix parsing (local gyms use Font), 2FA, open self-signup
  + email infrastructure, admin protocol-tuning dashboard, system-health
  analytics.


## Remaining implementation-level decisions

Not real design forks (no significant trade-off), so decide these
sensibly during the relevant build phase rather than re-litigating:
session cookie expiry/"remember me" behavior; the exact seed content of the
default `plate_inventory_items` and starter `grip_types` list; standard
CRUD editability of past `WorkSet`/`Climb`/`TrainingSession` entries.
