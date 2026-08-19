---
name: orchestrate
description: >-
  Orchestrate several GitHub issues end-to-end: map the dependency graph into
  parallel/blocked waves, dispatch each ticket to a cheap subagent in an
  isolated worktree, integrate green branches into local main, open one batch
  PR, run an adversarial code review with a stronger model, fix the union of
  findings, and stop for the owner's merge/deploy go. Use when the owner says
  "orchestrate these issues", lists several issue numbers to build, or says
  "continue" to resume an in-flight orchestration.
---

# Orchestrate a batch of issues

You are the **orchestrator**. You do not write ticket code yourself — you plan,
dispatch subagents, integrate, gate, and review.

Read `CONTEXT.md` for domain language and `docs/agents/issue-tracker.md` for
`gh` conventions before starting.

---

## Hard gates (never violate)

- **Subagents never push, open PRs, or merge.** They commit to a named branch
  only.
- **Merge only to LOCAL main, `--no-ff`, never push** — until the batch PR
  step.
- **Run `scripts/pre-merge-check <branch>` before every merge.** Stale base or
  conflicts → rebase/cherry-pick first, don't merge blind.
- **The loop STOPS at "PR reviewed + findings resolved."** Merging the PR and
  deploying wait for the owner's explicit go (see code-change gate). Docs-only
  / tooling batches may auto-merge per project conventions.
- **Never infer merge behavior from `git diff A..B`** (a tip-to-tip diff is not
  what a 3-way merge does). Use `pre-merge-check` / `git merge-tree`.

---

## Reactive execution (never violate)

> [!CAUTION]
> **NEVER poll or loop-check subagents.** The messaging system notifies you
> automatically when a subagent finishes. After dispatching subagents, either
> proceed with independent work or stop calling tools and wait for the system
> to wake you up.
>
> Do NOT set short timers (5s, 10s, 30s) to check on subagent progress. Do NOT
> call `manage_task status` in a loop. If you must set a safety timeout, use a
> generous duration (≥ 10 minutes) with the subagent's conversation ID as the
> `TimerCondition` so the timer cancels automatically on completion.

---

## Model tiers

| Role | Subagent Type | Model tier | Rationale |
|------|---------------|------------|-----------|
| Orchestrator (you) | — | `inherit` | Planning + integration needs full context |
| Implementer subagents | `self` | `flash` | Cheap, fast, inherits write tools, scoped to one ticket |
| Adversarial reviewer | `research` (or `self`) | `pro` | Deep reasoning catches subtle failures |

---

## Phase 0 — Map the graph

1. Read each issue: `gh issue view N --repo <owner/repo>`. Note blocked-by /
   blocking. Umbrella PRDs close when their child slices land — they aren't
   code.
2. Build the dependency spine: what's **independent** (dispatch now, in
   parallel) vs **blocked** (wait for its dep to merge). Watch shared-resource
   races: the conda env is shared across worktrees, so a ticket that mutates it
   (uninstalls deps) must run ALONE.
3. State the wave plan in one short message and start. A plain "continue" =
   resume the current plan without re-explaining.

## Phase 1 — Dispatch one subagent per ticket

For each ready ticket, create a git worktree and launch a subagent:

```bash
git worktree add .worktrees/ticket-<N>-<slug> -b ticket-<N>-<slug> main
```

Launch with `invoke_subagent`, `TypeName: "self"`, `Model: "flash"`. Give a self-contained prompt
containing:

- Which issue, what to read, exact scope + acceptance criteria.
- Working directory and branch name explicitly.
- **Base-freshness clause (always):** *"First verify your worktree is on
  branch `ticket-<N>-<slug>` based on current `main`."*
- Run `scripts/test` + `scripts/lint` in the worktree — both must pass.
- Commit to branch `ticket-<N>-<slug>` with conventional message.
- **"Do NOT push, open a PR, or merge."**

Keep prompts scoped (explicit file map, targeted tests then full suite once) to
control token spend.

**After dispatching: stop calling tools.** The system will notify you when each
subagent completes.

## Phase 2 — Integrate each green branch

When an agent reports done:

1. `scripts/pre-merge-check ticket-<N>-<slug>`. If **stale base**: cherry-pick
   its unique commits onto main or have it rebase — its own test run reflected a
   stale tree, so don't trust that green until it's re-based. If **conflicts**:
   resolve deliberately.
2. `git merge --no-ff ticket-<N>-<slug>` into local main.
3. Run the **full** suite on main (`scripts/test` + `scripts/lint`). Report the
   merge concisely.
4. Now-unblocked tickets become ready — dispatch them (back to Phase 1).

## Phase 3 — Open one batch PR

When all tickets are merged to local main:

1. Push a feature branch at main's tip:
   `git push origin main:<batch>-batch`
   (or create a local branch first if main is branch-protected).
2. `gh pr create --base main --head <batch>-batch` with a body that lists each
   issue, the verification (test/lint counts), and anything deferred/manual.

## Phase 4 — Adversarial review

Launch a single strong reviewer subagent (`invoke_subagent` with `TypeName: "research"` or `"self"`, `Model: "pro"`) using the
failure-hunting prompt template below. **Do NOT poll for completion** — wait for
the system to notify you.

If GitHub Copilot review is available, request it in parallel:
```bash
gh api repos/<owner/repo>/pulls/<N>/requested_reviewers \
  -X POST -f "reviewers[]=copilot-pull-request-reviewer[bot]"
```
If the request fails (quota, permissions), note it and move on — the Pro
reviewer is the primary gate.

### Reviewer prompt template (failure-hunting)

> Review PR #`<N>` (`<branch>` → `main`), diff `git diff origin/main..<branch>`.
> This batch closes #`<list>` — read each issue to judge spec adherence.
> Beyond that, HUNT failures, don't summarize:
> - For every path that accepts untrusted input (uploads, form/query params,
>   file parsing): enumerate concrete inputs that cause an **unhandled exception
>   or wrong HTTP status** (e.g. a 500 that should be a 400). Trace every
>   `raise`/`except`.
> - Every numeric/text input bounded with a security test?
> - Per-user data isolation: can user A ever read/write user B's rows?
> - Migrations in lockstep with model changes? Depth in modules, shallow
>   routers?
> Rank findings most-severe first with file:line, the failure scenario, and a
> fix. Separate must-fix from nice-to-have. Do NOT change code — I triage and
> apply.

### Triage and fix

When the reviewer reports back:

1. **Read the affected code first** before writing any fix or test. Understand
   the actual file names, class names, error messages, and code paths — do not
   guess.
2. Fix real defects test-first: write a regression test that fails, then apply
   the fix. Keep the suite green.
3. Accept nice-to-haves with a one-line rationale.
4. Commit and push fixes to the batch branch.

## Phase 5 — Cleanup and hand back

1. **Remove worktrees** and delete ticket branches:
   ```bash
   for d in .worktrees/ticket-*; do
     [ -d "$d" ] || continue
     branch=$(basename "$d")
     git worktree remove --force "$d" 2>/dev/null
     git branch -D "$branch" 2>/dev/null
   done
   ```
2. **Report** to the user: what merged, test/lint counts, review outcomes,
   findings fixed, and anything still on the owner (manual steps, the
   merge/deploy go).
3. **Do not merge or deploy the PR** without an explicit go.

---

## Resumability

Keep a short status note (which tickets merged, which subagent is in flight,
batch PR + review state, resume recipe). Update it at each merge and before the
PR/review steps so a fresh session (or "continue") can pick up exactly where
this left off.
