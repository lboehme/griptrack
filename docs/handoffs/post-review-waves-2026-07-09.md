# Handoff — full-review re-plan + Waves 0–2 shipped and deployed

2026-07-09. Fresh-agent continuation doc. Read `CLAUDE.md` + `CONTEXT.md`
first, plus the previous handoff (`post-pwa-reliability-2026-07-08.md`) —
its process gotchas still bind.

## What happened this session

1. **Planning:** full critical review (`docs/griptrack-full-review.md`)
   was grilled decision-by-decision with the owner → **ADR 0006**
   (personal instrument, open-sourcing as candidate growth path,
   public-launch track dropped) + a wave-based roadmap in `CLAUDE.md` +
   issues #50–#59.
2. **Waves 0–2 built, reviewed, merged, deployed to Fly.** Issues #50–#58
   all closed via PRs #61–#63, #65–#71. Production verified directly:
   Alembic head `a623146e0d0d`, `users.session_version` present, health
   200. Note: the deploy invalidated all existing sessions (deliberate —
   session revocation rollout); everyone logs in once.
3. **Docs updated** (this PR): CLAUDE.md current-state/domain/roadmap,
   CONTEXT.md glossary (SessionNumber, Deload, PainReport, Voided
   MaxWeightTest; edge_mm/pinch note landed earlier via #65).

## How it was built (worked well — reuse)

Owner-directed multi-model pipeline to save Fable-tier tokens: **Sonnet 5
agents code (always instructed to invoke the project `/tdd` skill),
Opus 4.8 agents review (diff-focused, told exactly which files/refs to
read), Fable orchestrates, resolves merges, and does final checks.**
Owner also had an external LLM draft several slices (#65–#70 originally);
the Opus reviews caught real bugs in those (see below), so **always
code-review external/weak-model PRs before merging**.

Merge mechanics that mattered:
- Branch protection requires CI-green and up-to-date branches; auto-merge
  is disabled → use background `gh pr checks --watch` + `gh pr merge`
  loops, and expect to merge main into each successive branch (squash
  merges make identical stacked content conflict — resolution is almost
  always "take main's side" for previously-merged content).
- Stacked branches (migration chains) must merge in order; regenerate any
  migration whose `down_revision` went stale (`scripts/new-migration`,
  never hand-edit). SQLite needs `server_default` on new NOT NULL
  columns — CI's empty-DB gates can't catch that; test against a
  populated DB.
- `scripts/lint` gate: when a module newly builds SQLModel query
  expressions, add it to the pyproject `[[tool.mypy.overrides]]` list
  rather than re-broadening disabled codes.

Review catches worth remembering (the pipeline's value proof): PRG-break
double-submit on climb warning; `/offline` missing from the service-worker
content hash; global mypy disable killing None-safety; NOT NULL migration
without server_default (prod-deploy breaker); duplicate pain-report rows
from double-bound JS events; export endpoint that was UI-unreachable;
unbounded `session_number`; home route bypassing `session_version`.

## Where things stand

- **Deployed:** everything through Wave 2 + review-debt cleanup (#71),
  173 tests, ruff/mypy/pip-audit clean.
- **Next up: Wave 3 — Asymmetry Analytics** (#45–#48, ready-for-agent,
  already sliced). Then **Wave 4** (#59) needs its own mini-grill before
  slicing.
- **Owner-gated, unchanged:** Oracle account still stuck (support
  ticket) → Litestream enable + restore drill is step one when it clears;
  tripwire from planning: if still stuck ~a week after 2026-07-09,
  revisit decoupling backups to R2/B2. PWA phone test + accessibility
  mini-pass still pending. Error-tracking decision post-Oracle.
- **Deferred with named triggers:** see CLAUDE.md "Roadmap (open)".

## Gotchas discovered this session

- A failed CI email/notification can be stale — check `gh run list` for
  the branch before reacting; two mid-session failures were already
  healed by later pushes.
- `set -o pipefail` when gating on `scripts/lint | tail` — a pipe eats
  the exit code otherwise (one push went out with a mypy error that way).
- Background subagents in worktrees: one agent `cd`'d into the shared
  main checkout by mistake (self-repaired, verified no damage) — when
  spawning agents, state the worktree path explicitly and verify branch
  state on disk afterwards; also pre-merge main into branches yourself
  before dispatching fix agents, or they burn tokens re-resolving known
  conflicts.
- `client.cookies.set()` in TestClient doesn't reliably reattach a cookie
  after `/logout` clears the jar — send a raw `Cookie:` header in
  revocation tests.
