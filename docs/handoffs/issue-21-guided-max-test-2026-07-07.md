# Handoff — next session: issue #21 (guided max test, single-hand ladder)

2026-07-07. Fresh-agent continuation doc. Read `CLAUDE.md` + `CONTEXT.md`
first; this covers only what they and the tracker don't.

## Where things stand

Issue #24 (session estimated-max fallback) is **done**: PR #31 squash-merged,
issue auto-closed, deployed to fly.io and verified (health 200, migration
`2d4a056193f4` applied with pre-migration backup). Owner still intends to
verify the warmup flow on their phone.

## Next up: #21

- Spec lives in issue #21 (`lboehme/griptrack`); PRD for the whole guided
  max-testing routine is in a comment on #14. Don't re-derive.
- Chain: #21 → #22 (two-hand interleaved) → #23 (entry-point wiring).
- **Collision note (now resolved one way):** #24 landed first, so #23 must
  reconcile with the reworked warmup notice — it now shows per-hand
  estimate-entry forms (`SessionMaxEstimate`, see CONTEXT.md) alongside the
  max-test link, and hands render independently (`planned_hands` /
  `untested_hands` in `training_log.warmup_view`).
- The two "estimated max" concepts stay separate by design: #24's stored
  per-session `SessionMaxEstimate` vs #14/#21's transient guided-test seed
  input. Do not unify them.

## Conventions that bind (short form — details in CLAUDE.md)

- TDD at the HTTP seam only (`tests/conftest.py`, drivers in
  `tests/helpers.py`); seam pre-agreed for the #14 PRD — don't re-ask.
- Migrations via `scripts/new-migration`, never hand-written; CI gate =
  `scripts/test` + `scripts/check-migrations`.
- New numeric/text inputs: bound in `backend/limits.py` + security test.
- Unit-specific logic mirrors per unit (ADR-0003), never converts — matters
  for #21's increment ladders.
- Pipeline: issue → branch → PR → CI `test` check → squash merge (auto-closes
  issue) → manual `scripts/deploy`. Merge does NOT auto-deploy.

## Small leftovers from #24's code review (optional warm-up tasks)

1. Dedupe `trained_combinations` / `tested_combinations` in
   `backend/training_log.py` (shared dict-building tail).
2. Drop the unused `training_session=None` default on `compute_ramp_plan`.
3. `worksets_view` docstring still says "prefills from CurrentMax" (now
   `effective_max`).
4. Move the estimate weight-ceiling test into `tests/test_security.py`'s
   `test_absurd_numeric_inputs_are_rejected` for one audit surface.
5. Latent trap noted, no action needed: `/session/estimate`'s htmx 204 branch
   is unreachable from the UI (plain form); if someone later adds `hx-post`
   with `hx-swap="none"`, the ramp won't render until reload.

## Suggested skills

- `tdd` — invoke before writing any #21 code.
- `code-review` (against `main`) — before merging the #21 branch.
- `verify` / `run` — before merging; it's a UI-heavy flow.

## Working style of the owner

Terse approvals; one question at a time with a recommendation; builds
nothing themselves; direct-to-main OK for small infra, features via PR;
verifies UI personally on their phone after deploys.
