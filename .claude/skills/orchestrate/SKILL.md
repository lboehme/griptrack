---
name: orchestrate
description: >-
  Orchestrate several GitHub issues end-to-end: map the dependency graph into
  parallel/blocked waves, dispatch each ticket to a cheap Sonnet worktree
  agent running /implement, integrate green branches into local main, open one
  batch PR, run a dual code review (GitHub Copilot + a deep Opus pass), fix the
  union of findings, and stop for the owner's merge/deploy go. Use when the
  owner says "orchestrate these issues", lists several issue numbers to build,
  or says "continue" to resume an in-flight orchestration.
---

# Orchestrate a batch of issues

You are the **orchestrator** (Fable/Opus tier). You do not write ticket code
yourself — you plan, dispatch cheap agents, integrate, gate, and review.
GripTrack-specific working style lives in the `griptrack-subagent-orchestration-style`
and `griptrack-workflow` memories; this skill is the procedure. Read
`docs/agents/issue-tracker.md` for `gh` conventions.

## Hard gates (never violate)
- **Agents never push, open PRs, or merge.** They commit to a named branch only.
- **Merge only to LOCAL main, `--no-ff`, never push** — until the batch PR step.
- **Run `scripts/pre-merge-check <branch>` before every merge.** Stale base or
  conflicts → rebase/cherry-pick first, don't merge blind.
- **The loop STOPS at "PR reviewed + findings resolved."** Merging the PR and
  deploying wait for the owner's explicit go (see `griptrack-workflow`:
  code-change gate). Docs-only/tooling batches may auto-merge per that memory.
- **Never infer merge behavior from `git diff A..B`** (a tip-to-tip diff is not
  what a 3-way merge does). Use `pre-merge-check` / `git merge-tree`.

## Phase 0 — Map the graph
1. Read each issue: `gh issue view N --repo lboehme/griptrack`. Note blocked-by
   / blocking. Umbrella PRDs close when their child slices land — they aren't code.
2. Build the dependency spine: what's **independent** (dispatch now, in parallel)
   vs **blocked** (wait for its dep to merge). Watch shared-resource races: the
   conda env `griptrack` is shared across worktrees, so a ticket that mutates it
   (uninstalls deps) must run ALONE.
3. State the wave plan in one short message and start. A plain "continue" =
   resume the current plan without re-explaining.

## Phase 1 — Dispatch one agent per ticket
For each ready ticket, launch a background agent:
`Agent(subagent_type: "general-purpose", model: "sonnet", isolation: "worktree")` — never fork.
Give a self-contained prompt containing:
- Which issue (`gh issue view N`), what to read, exact scope + acceptance criteria.
- **"Invoke the project `/implement` (or `/tdd`) skill"**: test-first at the HTTP
  seam, `scripts/test` + `scripts/lint` green, `/code-review` on any change that
  touches a module boundary/interface, commit to branch `ticket-<N>-<slug>`.
- **Base-freshness clause (always):** *"First verify your worktree is based on
  current `main` (`git merge-base HEAD main` must equal main's HEAD). If not,
  rebase onto it before working, and report your base SHA."*
- **"Do NOT push, open a PR, or merge."**
Keep prompts scoped (explicit file map, targeted-tests-then-full-once) to control
Sonnet token spend.

## Phase 2 — Integrate each green branch
When an agent reports done:
1. `scripts/pre-merge-check ticket-<N>-<slug>`. If **stale base**: cherry-pick its
   unique commits onto main (`git cherry-pick <shas>`) or have it rebase — its own
   test run reflected a stale tree, so don't trust that green until it's re-based.
   If **conflicts**: resolve deliberately.
2. `git merge --no-ff ticket-<N>-<slug>` into local main (or land the cherry-picks).
3. Run the **full** suite on main (`scripts/test`, `run_in_background: true` — it
   exceeds the 120s foreground default) + `scripts/lint`. Report the merge concisely.
4. Now-unblocked tickets become ready — dispatch them (back to Phase 1).

## Phase 3 — Open one batch PR
When all tickets are merged to local main:
1. Push a feature branch at main's tip (main is branch-protected):
   `git branch <batch>-batch main && git push -u origin <batch>-batch`.
2. `gh pr create --base main --head <batch>-batch` with a body that lists each
   issue, the verification (test/lint counts), and anything deferred/manual
   (e.g. an on-device step). One integration PR for a dependency-linked batch.

## Phase 4 — Dual review (the important upgrade)
Two reviewers with different failure modes catch different things — run both.
1. **Request Copilot immediately (instant, async):**
   `gh api repos/lboehme/griptrack/pulls/<N>/requested_reviewers -X POST -f "reviewers[]=copilot-pull-request-reviewer[bot]"`.
   Then **verify by real state, not the POST echo** (an empty `requested_reviewers`
   in the response is normal — Copilot reviews faster than it serializes):
   `gh api repos/lboehme/griptrack/pulls/<N>/reviews --jq '.[] | {user:.user.login,state:.state}'`
   and its inline comments via `.../pulls/<N>/comments --jq '.[] | {path,line,body}'`.
   **Always `--jq`-filter `gh api`** — unfiltered dumps flood context.
2. **In parallel, launch a deep Opus review** (`Agent(model: "opus")`) using the
   failure-hunting prompt below — not a generic "review this."
3. **Triage the union** of Copilot + Opus findings in ONE pass. Fix real defects
   test-first (a Copilot-style 500→400 gap deserves a regression test); accept
   nice-to-haves with a one-line rationale. Keep the suite green.
4. Push fixes, then **re-request Copilot** on the fixed commit as a final cheap gate.

### Opus reviewer prompt template (failure-hunting)
> Review PR #<N> (`<branch>` → `main`), diff `git diff <merge-base>..HEAD`. Invoke the
> project `code-review` skill. This batch closes #<list> — read each issue to judge
> spec adherence. Beyond that, HUNT failures, don't summarize:
> - For every path that accepts untrusted input (uploads, form/query params, file
>   parsing): enumerate concrete inputs that cause an **unhandled exception or wrong
>   HTTP status** (e.g. a 500 that should be a 400). Trace every `raise`/`except`.
> - Every numeric/text input bounded (`backend/limits.py`) with a security test?
> - Per-user data isolation: can user A ever read/write user B's rows?
> - Migrations in lockstep with model changes? Depth in modules, shallow routers?
> Rank findings most-severe first with file:line, the failure scenario, and a fix.
> Separate must-fix from nice-to-have. Do NOT change code — I triage and apply.
> [Add any per-ticket "expected, don't flag" notes, e.g. a deliberately-deferred
> manual step.]

## Phase 5 — Stop and hand back
Report: what merged, test/lint counts, both reviews' outcomes, findings fixed, and
anything still on the owner (manual steps, the merge/deploy go). **Do not merge or
deploy the PR** without an explicit go.

## Resumability
Keep a short status memory (see `android-pivot-orchestration-status` for the shape):
which tickets are merged, which agent is in flight, the batch PR + review state, and
the resume recipe. Update it at each merge and before the PR/review steps so a fresh
session (or "continue") can pick up exactly where this left off. Mirror the live
plan in a Task list too.
