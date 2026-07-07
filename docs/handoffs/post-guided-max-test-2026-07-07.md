# Handoff — next session: guided max-testing done, PWA Tier 1 next

2026-07-07 (evening). Fresh-agent continuation doc. Read `CLAUDE.md` +
`CONTEXT.md` first; this covers only what they and the tracker don't.

## Where things stand

The whole guided max-testing routine is **done and deployed**: #21
(single-hand ladder, PR #33) → #22 (two-hand interleaved, PR #34) → #23
(entry-point wiring, PR #35), each squash-merged and deployed to fly.io
(health verified; no schema changes in any of them). Parent PRDs #14 and
#17 are closed. Owner still intends to try the routine on his phone.

PR #36 (deepen guided ladder state: passive hand's state as one opaque,
module-owned JSON token instead of 10 loose `other_*` form params) was
merged and deployed by the owner right after this doc — treat it as
landed. The `guided_max_test` module now owns that wire format
(`encode_column`/`decode_column`, `advance_two_hand`, `start_columns`);
decode re-validates everything, so tampered tokens → 400.

## Next up

- **PWA Tier 1** is the labeled `ready-for-agent` work: #26 (manifest,
  icons & head wiring) → #27 (service worker: caching, offline fallback,
  versioning), both children of PRD #19. Start with #26.
- Or triage: #29 (reliability hardening), #28 (injury-risk guardian —
  build only after Asymmetry Analytics per CLAUDE.md), #20 (offline
  WorkSet sync — needs design first).

## Process gotchas learned this session (will bite you otherwise)

- **Branch off `origin/main`, never local `main`.** This repo's worktrees
  carry a stale local `main` ref; branching from it after a squash-merge
  made PR #34 report CONFLICTING (add/add on every file). Fix was
  `git rebase --onto origin/main <old-base> <branch>` + force-push.
- `gh pr merge --delete-branch` errors with "main is already checked out"
  because the primary checkout holds `main` — the **merge itself
  succeeds** (verify via `gh pr view --json state`); just delete the
  remote branch separately with `git push origin --delete <branch>`.
- Merge does NOT auto-deploy — run `scripts/deploy` after, from a
  worktree whose HEAD content matches `origin/main` (check
  `git diff HEAD origin/main --stat` is empty).

## Conventions that bind (short form — details in CLAUDE.md)

- TDD at the HTTP seam only (`tests/conftest.py`, drivers in
  `tests/helpers.py`). Two-hand guided tests parse hidden fields with
  `html.unescape` (the ladder-state token is JSON in an attribute).
- New numeric/text inputs: bound in `backend/limits.py` + security test
  in `tests/test_security.py::test_absurd_numeric_inputs_are_rejected`.
- Migrations via `scripts/new-migration`; CI gate = `scripts/test` +
  `scripts/check-migrations`.
- Pipeline: issue → branch (off origin/main) → draft PR → CI `test`
  check → owner says merge → squash merge → `scripts/deploy`.

## Unqueued improvement backlog (from today's architecture review)

Candidates the owner saw but didn't schedule — don't start unprompted,
but they're pre-vetted if he asks for cleanup work:

1. **Combo value object** for (hand, grip_type_id, edge_mm) — CONTEXT.md
   names the concept everywhere; code passes 3–4 loose params through
   ~20 signatures; `hand in ("left","right")` validated in 4 places.
2. **Collapse `trained_combinations`/`tested_combinations`** in
   `backend/training_log.py` (~50-line near-twins; also in the old #24
   handoff) + fold single-caller pass-throughs (`worksets_for_combo`).
3. **`other_hand()` policy helper** beside `hands_for` — the pairing rule
   is re-derived in `warmup.html` Jinja and the guided router.

Still-open small leftovers from #24's review: drop the unused
`training_session=None` default on `compute_ramp_plan`; fix
`worksets_view` docstring ("prefills from CurrentMax" → `effective_max`);
move the estimate weight-ceiling test into `test_security.py`.

## Working style of the owner

Terse approvals; one question at a time with a recommendation; builds
nothing himself; verifies UI personally on his phone after deploys.
"Wait/stop before coding" is a hard gate — hold at design summary until
an explicit go. He may cap effort ("15% budget left") — compress
ceremony, keep the tests. Skip `/code-review` when he says the build is
small; otherwise run it against `origin/main` before the PR.
