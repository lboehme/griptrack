# Test-suite review — security & completeness audit (2026-07-09)

Critical review of `tests/` against the code on `main` after the Wave 0–2
merges (#61–#71, tip `2c88f3f`). Question asked: do the tests completely
and securely cover all current functionality, and is the test code itself
sound?

## Method and verification result

Everything was re-verified from scratch in a clean environment (fresh
venv, Python 3.11), not taken from CI's word:

- **`scripts/test`: 173/173 tests pass** (was 131 before today's waves).
- **`scripts/check-migrations`: both gates pass** (fresh upgrade to head
  `a623146e0d0d`; no model/migration drift).
- **`ruff` and `mypy`: clean.** (`pip-audit` not re-run here — no
  registry access from the review environment; CI covers it.)
- **Line coverage measured with `pytest --cov=backend`: 97 %**
  (1195 statements, 35 missed). The missed lines are what several
  findings below point at — coverage numbers are in the finding text so
  they can be re-checked with the same command.

**Verdict up front:** the suite is in genuinely good shape — every
feature shipped today arrived with tests, the per-user isolation
discipline is applied consistently to the new surfaces (pain reports,
session meta, voiding, estimates, multi-session days), and the
revocation/rate-limit tests are carefully engineered (raw-`Cookie`
header trick, bystander non-revocation, right-password-while-blocked).
The gaps below are real but bounded, and two of them cluster on one
feature: the CSV export is the least-tested new code in the app, and it
is exactly the kind of code (bulk data egress, join-based scoping) that
most deserves hostile tests.

## Findings — security-relevant

### S1. The session-data half of the CSV export is never executed by any test (high)

`backend/routers/profile.py` lines 129–155 — the branch that writes
`TrainingSession.csv`, `WorkSet.csv`, `PainReport.csv`,
`WarmupStepCheck.csv`, and `SessionMaxEstimate.csv` — has **zero
coverage**. The only export test
(`test_csv_export_returns_user_scoped_data`) exports a user who has no
training sessions, so only the three directly-user-scoped files are
exercised.

Why this matters more than an ordinary coverage hole: the untested
branch is the only place in the app where data is scoped *indirectly*,
via `training_session_id.in_(ts_ids)` — the classic shape for a
cross-user leak to slip in during a refactor. The one file whose
isolation is asserted (BodyWeightLog) is the trivially-scoped kind.
Today the queries are correct (verified by reading them), but nothing
pins that.

Also untested on the same endpoint:

- **No unauthenticated test.** `GET /profile/export` depends on
  `auth.current_user` (verified in code), but no test asserts the 401 —
  for the single highest-value data-egress URL in the app.
- **Absent-vs-empty inconsistency** (unpinned behavior): a user with no
  sessions gets *no* `TrainingSession.csv`/`WorkSet.csv` at all
  (`if ts_rows:` guard), while `MaxWeightTest.csv` etc. are written even
  when empty. Whichever is intended, a test should say so.

### S2. No structural "every route requires auth" sweep (medium)

Exactly one test asserts a 401 (`/invites`). Every other protected route
relies on the author having remembered `Depends(auth.current_user)` —
and today's own review cycle caught precisely this class of bug before
merge (the home route bypassing `session_version`, per the handoff). A
single parametrized test that walks every registered route (FastAPI
exposes `app.routes`), fires an unauthenticated request, and asserts
401/redirect — with an explicit allowlist for the public routes
(`/`, `/health`, `/login`, `/register`, `/offline`, `/sw.js`,
`/manifest.webmanifest`, static) — would turn "remembered every time"
into "enforced by the suite", including for every future route.

### S3. Pain-report severity bound has no test (medium — house-rule violation)

`/session/pain-report` bounds severity with `ge=1, le=3`
(`backend/routers/training_session.py`), but no test posts severity `0`,
`4`, or `-1` — every test uses 1–3. CLAUDE.md's standing rule is "when
adding a route that takes numbers or user text, bound it **and add a
security test**". The note-length and hand-whitelist tests for the same
endpoint exist and are good; the numeric bound is the one missing.

### S4. Voiding is only tested in its simplest configuration (medium)

`test_user_can_void_their_own_max_test` (void the only test → combo
untested) and `test_user_cannot_void_someone_elses_max_test` (403) are
both good. Untested:

- **Fallback semantics**: voiding the *newest* of two tests must
  resurface the older one as CurrentMax — and work sets logged since
  that older test's date must re-enter the supersede rule. This is the
  actual point of `voided_at` filtering in `latest_max_test`, and it's
  the subtlest logic the feature touches (`training_log.py:502`).
- **Analytics exclusion**: no test that a voided test drops out of the
  dashboard combos / correlation (`_best_pull_at`,
  `trained_combinations`, `last_used_combination` each grew a
  `voided_at.is_(None)` filter; none is asserted through the HTTP seam).
- **Rendering**: the voided row's struck-through display and the absence
  of a second Void button (`max_tests.html:44–54`) are unasserted.
- Note while reading: the code comment at
  `backend/routers/max_tests.py` ("Fetch all max tests (unvoided)") does
  not match the query, which deliberately fetches voided rows too so the
  template can strike them through. The comment should be fixed before
  someone "fixes" the query to match it.

### S5. New user-text fields have no escaping (XSS) pin tests (low)

`test_name_is_rendered_inert_not_executed` sets the precedent: user text
gets an escaping test. Today added three new user-text-to-HTML paths —
session notes and pain-report notes (rendered on the worksets page),
climb grade (rendered into `data-grade` attributes and list items) — and
none has one. Jinja2 autoescape currently protects all of them (verified:
no `|safe` anywhere under `backend/templates/`), so this is
defense-in-depth, but the pin is one cheap test per field and protects
against a future `|safe` or JS-side rendering change.

### S6. CSV formula injection is neither neutralized nor tested (low)

Export cells are written verbatim; a note or grade beginning with `=`,
`+`, `-`, or `@` will be executed as a formula by Excel/LibreOffice on
import. Severity is low because the export is strictly self-scoped — the
victim would have to attack themselves — but it becomes real the moment
exports are ever shared (a coach, a physio). Standard fix is prefixing
risky cells with `'`; if instead the decision is "accepted risk for a
personal instrument" (consistent with ADR 0006), record that in a test
comment or the ADR rather than leaving it undecided.

## Findings — functional coverage gaps

### F1. Untested error branches (all confirmed by coverage)

- `/session/create` with `page` outside warmup/worksets → 400
  (`training_session.py:102`).
- `POST /max-tests` with an invalid hand or unknown grip type → 400
  (`max_tests.py:56, 58`).
- `POST /profile` with an invalid `hand_order_pref` → 400
  (`profile.py:77`).
- Admin reset for an unknown email → 404 (`routers/auth.py:35`).
- Registration with an invalid `unit_pref` → 400 (`auth.py:139`).
- Empty grip-type name early-return (`max_tests.py:73`).

### F2. The login and register pages are never GET-requested

`GET /login` and `GET /register` (`routers/auth.py:41, 74`) have zero
coverage — the two entry pages of the app have no smoke test. A template
regression (broken Jinja variable, missing form field name) would ship
silently today.

### F3. One response mode of each autosave endpoint is untested

The worksets/warmup POSTs are tested via their plain-form redirect path
but never with `HX-Request` (204 paths at `training_session.py:160, 182,
227` uncovered), while `/session/update` and `/session/pain-report` are
tested only via `HX-Request` (redirect paths at 254, 290 uncovered).
Each endpoint should be exercised in both modes at least once — the
htmx-vs-fallback split is real production behavior on both sides.

### F4. Correlation floor tested far from the boundary

The n ≥ 8 floor is asserted with n=8 (positive) and n=1 (negative).
The boundary case — exactly 7 parseable points → no correlation — is the
one a future off-by-one would flip. One test, one climb short.

### F5. `volume.svg` 404-on-empty is untested

`dashboard.py:25`. This is also quietly the isolation story for that
endpoint (a foreign user's combo yields an empty trend → 404 rather than
data), which deserves an explicit cross-user assertion in the style of
the other isolation tests.

### F6. Race-retry re-raise arm unreachable in tests

`training_log.py:277` (`IntegrityError` whose post-rollback re-fetch
still finds nothing → re-raise) is uncovered. Acceptable to leave — but
worth a comment in `test_session_race.py` acknowledging the arm is
deliberately untested rather than forgotten.

## Findings — test-code quality (review of the test files themselves)

### Q1. Stale references to a test file that doesn't exist

`tests/helpers.py` (`get_session_page` docstring) and
`tests/test_warmup.py:131` both point readers at
`test_past_session_creation.py`; the gate tests actually live in
`test_multi_session_days.py`. Rename or fix the references.

### Q2. `test_register_is_rate_limited`'s "valid registration" isn't valid

The final assertion registers with password `"long-pw"` — 7 characters,
below the 8-char minimum — so the request would 400 even without the
limiter. The test still detects a missing limiter (400 ≠ 429), but the
comment "Even a valid registration is blocked" is untrue as written; use
an 8+-char password so the test proves what it claims.

### Q3. Fixture seeds are hand-mirrored from the migrations

`conftest.py` now re-implements the seed data including the new
per-grip `dimension_name` ("block width" for pinch). The migration gates
verify *schema* lockstep, not *seed* lockstep — if the prod seed
migration and the fixture ever disagree (e.g. a future grip gets the
wrong dimension in one place), no gate catches it. Low risk today;
consider importing the seed values from one shared constant instead of
two copies. (`STARTER_GRIP_TYPES` is already shared; the
dimension-assignment rule is not.)

### Q4. Sound, documented deviations — no action

Two tests knowingly leave the HTTP seam and both carry clear
justifications: `test_session_race.py` (module-level, needs to inject a
commit mid-race) and `_seed_legacy_sport_climb` in `test_climbs.py`
(the seam can no longer create sport climbs by design). The
`test_db_pragmas.py` module-reload dance restores state in `finally`.
These are fine as-is.

### Q5. Assertion style is regex-on-markup throughout — consistent, slightly brittle

The suite's page parsers (`workset_rows`, `ramp_weights`,
`current_maxes`, …) bind tests to exact attribute layouts
(`data-*` hooks, attribute order in the `is_deload` check). This is a
deliberate, consistent idiom and the `data-*` hooks make it mostly
robust; just keep new assertions on `data-*` attributes rather than
free-form markup (the `'name="is_deload" checked' in page or
'checked name="is_deload"'` OR-pattern in `test_worksets.py` is the kind
to avoid).

## What is demonstrably strong (don't re-litigate at the grill)

- **Per-user isolation** is tested for every data surface, old and new:
  history, climbs, bodyweight, max tests, estimates, plates, guided
  flows (single and two-hand), pain reports + session meta (same-date
  collision test is particularly good), and void authorization.
- **Session revocation** testing is exemplary — including the bystander
  case and the raw-`Cookie`-header workaround with an explanation of the
  TestClient pitfall it avoids.
- **Rate limiting** covered on both `/login` and `/register`, including
  the right-password-while-blocked case.
- **Input bounds** tested for all pre-existing numeric inputs plus new
  `session_number`, climb grade/notes lengths, session/pain note
  lengths, and guided-test token tampering (malformed and absurd-value).
- **New-feature logic tests are behavioral, not cosmetic**: deload
  exclusion re-derives the plateau arithmetic; Spearman is fed
  deliberate ties; multi-session tests cover independence, latest-
  resolution, pinning, backfill, and the past-date gate; the cache
  version is proven to move when any hashed source moves, including the
  two templates behind `/offline`.
- **The gates themselves** (`scripts/test`, `scripts/check-migrations`,
  `scripts/lint`) all pass from a cold environment, so CI green is
  reproducible.

## Recommended next tests, in priority order

1. **Export with real session data + isolation** (S1): user A trains
   (work sets, pain report, estimate, warmup checks), user B trains on
   the same date; export B; assert all five session CSVs exist and
   contain only B's rows; assert unauthenticated export → 401.
2. **Route-walking auth sweep** (S2) — one parametrized test, permanent
   structural coverage.
3. **Severity bound test** (S3) — two lines, closes the house-rule gap.
4. **Void fallback + analytics exclusion** (S4).
5. **Escaping pins for notes/grade** (S5) and the **error-branch pack**
   (F1/F2 — mostly one-liners, includes the login/register page smokes).
6. **Both response modes per autosave endpoint** (F3), **n=7 correlation
   boundary** (F4), **volume.svg 404/isolation** (F5).
7. Test-code cleanups Q1–Q3 alongside whichever of the above lands
   first.

## Summary

All 173 tests pass and the measured coverage (97 %) is honest — the
suite tests behavior through the HTTP seam, not implementation detail,
and today's nine feature/hardening PRs all landed with meaningful tests
including isolation and bounds coverage. The material risks found are:
one high-value untested code path (the session-data half of the CSV
export, including its join-based user scoping), the absence of a
structural auth sweep, one missing numeric-bound test (pain-report
severity), and under-tested void semantics. None of these is an
observed vulnerability — the corresponding backend code was read and is
correct today — but all four sit where a future regression would be
both likely and quiet. The recommended tests are small (roughly a day
of work in total) and would bring the security-test posture up to the
same standard the rest of the suite already sets.
