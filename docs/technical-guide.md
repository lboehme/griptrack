# GripTrack — Technical Implementation Guide

*Snapshot as of 2026-07-08 (main @ d89fbd9). Written as grill input for a
design/architecture review; the companion piece is
`docs/product-overview.md`. Canonical terminology lives in `CONTEXT.md`;
recorded decisions in `docs/adr/`; agent-facing conventions in `CLAUDE.md`.*

## Stack at a glance

| Layer | Choice | Notes |
|---|---|---|
| Language/runtime | Python 3.12, uvicorn | Single stateless process |
| Web framework | FastAPI 0.139 | App factory in `backend/main.py` |
| ORM / schema | SQLModel 0.0.39 | One class = DB table + API schema |
| Migrations | Alembic 1.18 | From the start; seeds via migrations |
| Database | SQLite | One file on a persistent volume |
| Templates | Jinja2 + htmx | No build step, no SPA framework |
| Client JS | htmx 2 (vendored) + small inline handlers | Vanilla JS only where htmx can't reach |
| Charts | matplotlib → server-rendered SVG | No client-side charting library |
| Analytics deps | pandas, matplotlib | |
| Auth | `bcrypt` package directly + Starlette `SessionMiddleware` | Not passlib (unmaintained, incompatible with bcrypt ≥ 4.1) |
| Packaging | Docker (`Dockerfile` + `docker-entrypoint.sh`) | Host-agnostic |
| Backup | Litestream (baked into image, env-gated) | Continuous S3-compatible replication + boot-time restore |
| Hosting | Fly.io (production), Oracle Free Tier path merged but untested | Canonical URL `https://griptrack.duckdns.org` (DuckDNS → host; PWA installs are origin-bound so host switches must be DNS-only) |
| Tests | pytest + FastAPI `TestClient`, 131 tests | All at the HTTP seam |

Pinned runtime deps live in `requirements.txt`, test/dev extras in
`requirements-dev.txt`. Local dev uses a conda env named `griptrack`; run
from the repo root so `backend` resolves as a namespace package:
`conda run -n griptrack fastapi dev backend/main.py`.

## Repository layout

```
backend/
  main.py            app factory: middleware, routers, /health
  db.py              engine + get_session dependency (GRIPTRACK_DATABASE_URL)
  models.py          all SQLModel tables (shared type layer, not a "deep module")
  limits.py          upper bounds on every numeric input (DoS guard)
  auth.py            deep module: register/authenticate/session/invite/admin-reset
  plates.py          deep module: round_down_to_loadable + inventory CRUD
  training_log.py    deepest module: CurrentMax, ramp plans, autosave persistence
  guided_max_test.py deep module: stateless guided-test ladder + state tokens
  analytics.py       deep module: volume trend, plateau, overtraining, correlation
  charts.py          matplotlib SVG rendering (theme palettes, no pyplot state)
  templating.py      shared Jinja2 environment
  routers/           shallow HTTP adapters, one file per page/feature area
  templates/         Jinja2 pages + htmx partials (_-prefixed)
  static/            app.css, vendored htmx, PWA icons, register-sw.js
migrations/          Alembic env + 10 versioned revisions (seeds included)
tests/               19 files, HTTP-seam only, isolated SQLite per run
scripts/             test / check-migrations / new-migration / deploy /
                     oracle-deploy / generate-icons
deploy/              litestream.yml, oracle/ (compose, Caddy, setup-server)
docs/                deployment guides, ADRs, agent docs, session handoffs
```

## Module design

The organizing principle (from the `codebase-design` skill vocabulary):
**a small number of deep modules behind narrow interfaces, with
deliberately shallow routers**. Routers parse the request, call one module
function, render a template — depth never lives in a router.

- **`backend.auth`** — hides bcrypt hashing (8–72-char passwords — 72 is
  bcrypt's hard byte limit), the signed session cookie, invite
  generation/redemption, first-user-is-admin + bootstrap-token gating, a
  per-IP in-memory `LoginRateLimiter` (10 failures / 60 s), and the
  `current_user` / `require_admin` FastAPI dependencies that gate every
  per-user route.
- **`backend.plates`** — essentially one function,
  `round_down_to_loadable(target, inventory) -> weight`: a bounded
  single-stack subset-sum done in integer hundredths to avoid float
  drift (ADR-0002). Also seeds/edits the per-user inventory. This
  subset-sum is the DoS-sensitive path that motivates `backend.limits`.
- **`backend.training_log`** — the deepest module. Owns the `CurrentMax`
  rule (`compute_current_max`, with an `as_of` variant that is the *same
  single implementation* analytics uses), `effective_max` (CurrentMax →
  SessionMaxEstimate → None precedence for session pages only),
  `compute_ramp_plan` (protocol percentages × CurrentMax, plate-rounded),
  the page-view assemblers (`warmup_view`, `worksets_view`), autosave
  upserts (`record_work_set`, `record_session_estimate`,
  `toggle_warmup_check`), `start_or_get_session` (one TrainingSession per
  user+date, created on first interaction), and history/combination
  queries.
- **`backend.guided_max_test`** — the effort-rating ladder (per-unit
  increments, kg: +10/+5/+2/+1; lbs: +20/+10/+5/+2.5) and the
  statelessness machinery: all running state is threaded through the page
  via an opaque, module-encoded token (never loose form fields), so
  abandoning the flow writes nothing and only the terminal "That's
  enough" action persists a MaxWeightTest.
- **`backend.analytics`** — `training_volume_trend` (Σ weight×reps per
  session per combo), `plateau_flag` (last 4 sessions never beat the
  prior best), `overtraining_warning` (volume ≥ 1.25× trailing average
  **and** shorter-than-typical rest — both required),
  `strength_grade_correlation` (best CurrentMax across combos as % of
  bodyweight vs V-number; Font→V lookup table; needs ≥ 3 points with
  variance; Pearson r via `statistics.correlation`). Thresholds are
  module constants, flagged as revisit-once-real-data-exists.
- **`backend.charts`** — SVG rendering with matplotlib's `Figure` API
  (not pyplot, so no global state under concurrent requests); light/dark
  palettes tuned per the dataviz guidance.

Per the testing decision, these modules are **not** unit-tested in
isolation — all 131 tests cross the external HTTP seam via `TestClient`.
The internal seams exist but are unexercised as seams.

## Data model

All tables in `backend/models.py`; every weight column stores the owning
user's native unit (ADR-0003).

- **users** — email (unique), hashed_password, optional display `name`,
  `is_admin`, `unit_pref` (kg/lbs, fixed at signup), `hand_order_pref`
  (alternating/sequential).
- **invites** — one-time codes; `created_by` / `used_by` / `used_at`.
- **body_weight_logs** — dated series, not a mutable field (ADR-0001).
- **grip_types** — lookup table seeded with 5 display names; extensible
  via a form, no deploy needed.
- **max_weight_tests** — append-only, scoped per (hand, grip_type_id,
  edge_mm) (ADR-0001).
- **plate_inventory_items** — (weight, count) rows; single stack
  (ADR-0002); seeded per unit on registration.
- **training_protocols** — `ramp_percentages` ("50,65,80,90"),
  `base_work_set_reps` (5), `default_work_sets` (3); one global row with
  `user_id NULL`; per-user overrides are additive later (ADR-0005).
- **training_sessions** — one per user+date; exists from the first
  interaction (autosave, no submit).
- **warmup_step_checks** — ticked ramp steps; pure progress state.
  Warmup weights are computed, never stored.
- **session_max_estimates** — per-session stand-in max for untested
  combos; unique on (session, hand, grip, edge) at the schema level;
  never an analytics input.
- **work_sets** — (session, hand, grip_type_id, edge_mm, weight, reps,
  set_number, nullable rpe); the only persisted training performance.
- **climbs** — date, discipline (boulder/sport), free-text grade, style
  (fixed vocabulary, deliberately not a lookup table), notes.

Derived, never stored: **CurrentMax** (latest test superseded upward by
any heavier post-test work set; a newer-but-lower test still wins —
deliberate reset), **TrainingVolume**, **Plateau**, **OvertrainingWarning**.

## HTTP surface

Session-cookie-authenticated HTML/htmx endpoints; JSON only where noted.

- `GET /`, `GET /health`
- Auth: `GET|POST /login`, `POST /logout`, `GET|POST /register`,
  `POST /invites` (admin), `POST /admin/reset-password` (admin)
- Profile: `GET /profile`, `POST /profile` (prefs),
  `POST /profile/name`, `POST /profile/bodyweight`
- Plates: `GET /plates`, `POST /plates` (upsert; count 0 deletes)
- Max tests: `GET|POST /max-tests`, `POST /grip-types`
- Guided test: `GET|POST /max-tests/guided`, `POST /max-tests/guided/both`
  (two-hand), `POST /max-tests/guided/step` (ladder advance)
- Session: `GET /session/new`, `GET /session/warmup`,
  `POST /session/check` (toggle step), `POST /session/estimate`,
  `GET /session/worksets`, `POST /session/workset` (upsert),
  `POST /session/workset/delete`
- Climbs: `GET|POST /climbs`
- History: `GET /history`
- Dashboard: `GET /dashboard`, `GET /dashboard/volume.svg` (per-combo
  chart, `Cache-Control: no-store`)
- PWA: `GET /manifest.webmanifest`, `GET /sw.js` (generated JS),
  `GET /offline`

## Security model

Enforced in code, covered by `tests/test_security.py`:

- **Passwords**: bcrypt via the `bcrypt` package; 8-char minimum, 72-byte
  maximum enforced.
- **Sessions**: signed cookie (Starlette `SessionMiddleware`),
  `SameSite=Lax`, `Secure` when `GRIPTRACK_ENV=production`.
- **CSRF**: SameSite=Lax cookie plus an Origin-vs-Host check middleware
  that 403s cross-origin POSTs (requests without an Origin header pass —
  curl/tests/GET navigations).
- **Rate limiting**: per-IP in-memory login limiter with
  timing-equalized authentication (no user-exists oracle).
- **Headers middleware**: CSP (`default-src 'self'`; `unsafe-inline`
  script/style needed for htmx glue), `X-Frame-Options: DENY`, nosniff,
  `Referrer-Policy: same-origin`. HSTS is set at the proxy layer (Fly /
  Caddy).
- **Input bounds**: `backend/limits.py` caps every numeric input; the
  plate subset-sum is the DoS-sensitive path. **House rule: any new route
  taking numbers or user text gets a bound and a security test.**
- **Data isolation**: `current_user` dependency on every per-user route;
  dedicated cross-user isolation tests.
- **Registration**: invite-only (ADR-0004); first admin gated by
  `GRIPTRACK_BOOTSTRAP_TOKEN`, which is removed after bootstrap.

## Frontend approach

Jinja2 pages + htmx partials, mobile-first CSS with large touch targets,
no build step. Session logging is two consolidated pages (warmup
checklist, work-sets table), laid out per `hand_order_pref` — alternating
renders L/R columns per row; sequential runs one hand's full flow then the
other. **Every interaction autosaves** via htmx POSTs; there is no submit
step anywhere in session logging. Charts arrive as `<img src=…/volume.svg>`
with a theme query param matching light/dark.

### PWA (Tier 1)

`backend/routers/pwa.py` serves a generated manifest and a generated
service worker. Precache covers only the static shell (CSS, htmx, icons)
plus the `/offline` fallback; **authenticated pages are never cached** —
navigations are network-first with the offline page as catch. The entire
client-update mechanism is the `CACHE_VERSION` string, derived at
import/startup from a content hash of every precached asset's source —
the static files plus the offline page's templates (`offline.html`,
`base.html`) (see `_compute_cache_version` in `backend/routers/pwa.py`)
— it changes automatically whenever any of those files' bytes change,
with no manual bump step. Icons are generated by `scripts/generate-icons` (Pillow, dev-only dep).
Offline *logging* (background sync, IndexedDB) is explicitly out of scope
so far (issue #20, needs design first).

## Persistence, migrations, ops

- **SQLite on a persistent volume**, path via `GRIPTRACK_DATABASE_URL`.
  Rules out pure-serverless hosts; fine for the user count by design.
- **Alembic from day one**; 10 revisions. Seeds (grip types, global
  protocol) ship *in* migrations, so a fresh DB is fully usable after
  `alembic upgrade head`. **Never hand-write revisions** — use
  `scripts/new-migration "msg"` (autogenerates against a temp DB at
  head); `scripts/check-migrations` runs the two CI migration gates
  locally. Migrations must stay in lockstep with model changes.
- **Container boot** (`docker-entrypoint.sh`): `alembic upgrade head`,
  then uvicorn with `--proxy-headers` (trust platform TLS termination for
  Secure cookies and real client IPs).
- **Config is env-only**: `GRIPTRACK_ENV`, `GRIPTRACK_SESSION_SECRET`
  (hard startup failure if missing in production),
  `GRIPTRACK_DATABASE_URL`, `GRIPTRACK_BOOTSTRAP_TOKEN`, plus five
  Litestream values (bucket/endpoint/region/key/secret — setting the
  bucket switches replication on; currently inert, values not yet set).
- **Deploy**: `scripts/deploy` = fly deploy + health check + migration-log
  verification. An Oracle Always-Free path (`deploy/oracle/` with Docker
  Compose + Caddy, `scripts/oracle-deploy`) is merged but has never run
  against a real VM (account signup blocked). Migration plan when it
  clears: enable Litestream on Fly → provision VM → first boot
  auto-restores from the bucket → flip DuckDNS → scale Fly to zero;
  never two writers on one bucket path.

## Testing & CI

- 131 tests / 19 files, **all at the HTTP seam** (`TestClient` against an
  isolated SQLite DB per run) — a deliberate decision, not an accident;
  module internals are reachable but untested in isolation.
- Coverage spans auth/invites, profile, plates, max tests, guided test
  (incl. two-hand), warmup, worksets, session estimates, climbs, history,
  dashboard/correlation, PWA/service worker, names, health, and security.
- `scripts/test` wraps the conda env and passes pytest args through. CI
  (`.github/workflows/ci.yml`) calls the same `scripts/test` and
  `scripts/check-migrations`, so local and CI behavior cannot drift.
- Process: work test-first (project `tdd` skill); issues/PRDs live as
  GitHub issues on `lboehme/griptrack`.

## Decision record (read before re-litigating)

| ADR | Decision | Load-bearing because |
|---|---|---|
| 0001 | Bodyweight & max weight as time series | Historic analysis needs point-in-time values |
| 0002 | Real per-user plate inventory for rounding | Suggestions must be physically loadable |
| 0003 | Native-unit storage (kg *or* lbs per user) | Canonical-kg would give lb users unloadable numbers |
| 0004 | Invite-only registration, no email infra | Small known user group; kills a whole attack/ops surface |
| 0005 | TrainingProtocol as config row, not constants | Per-user overrides later without schema rework |

Non-ADR but equally deliberate: the guided max test is fully stateless
(state token in the page, single terminal write); SessionMaxEstimate
shares no storage or code path with the guided test's seed estimate;
analytics read `compute_current_max` directly and never `effective_max`.

## Known open threads

- Issue #20 — offline WorkSet logging/sync (needs a design grill first).
- Asymmetry analytics (no issue yet) → issue #28 finger-injury-risk
  guardian (explicitly sequenced after asymmetry; `OvertrainingWarning`
  is described as its crude single-grip prototype).
- Oracle migration blocked on account signup; Litestream configured but
  not yet enabled with real credentials.
- Analytics thresholds (plateau window, 1.25× spike factor) are
  placeholder heuristics awaiting real-data calibration.
- Owner phone-testing of the installed PWA still pending; UX notes
  expected to become a work batch.
