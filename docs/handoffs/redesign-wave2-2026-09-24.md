# Handoff: continue the GripTrack redesign (wave 2: session play onward)

Paste everything below the line into a fresh Claude Code session on `lboehme/griptrack`.

---

You're continuing the GripTrack app redesign. GripTrack is a FastAPI + Jinja2 + htmx app, with no build step. It runs on-device on an Android phone: an embedded CPython backend on `127.0.0.1` behind a WebView, built with Chaquopy. Claude Code builds all of it; the owner doesn't write code. Read `CLAUDE.md`, `CONTEXT.md` and `docs/agents/issue-tracker.md` first.

## Where things stand (as of 2026-09-24)

**Source of truth for the redesign:**
- **PRD #142**: ten decisions and eight slices, each a sub-issue.
- **ADRs:** `docs/adr/0013-single-user-install-with-device-sign-in.md`, `0014-session-play-as-server-driven-steps.md` and `0015-native-rest-bridge.md`.
- **Design spec:** `docs/ui-review-2026-09.md`. Its "Direction" section (D0–D8) and "Visual language" section (V1–V11) have exact CSS values. The prototype screenshots are `docs/screenshots/ui-review-2026-09/prototype-*.jpg`, and the topo asset is `docs/design/topo-map.svg`.

**Shipped on `main`:**
- #137 is the UI review and #143 the ADRs.
- #152 fixed #138–#141:
  - Rendering bugs.
  - Android insets and splash.
  - Session-URL restore and Back.
  - Touch polish, hold-to-repeat steppers, and the `human_date` / `display_name` Jinja filters.
- **#153** shipped two slices:
  - **S0 Look (#144):** dark-only colour tokens with every colour a token, bundled Barlow fonts, a fixed topo map in `base.html`, two glass levels, and component restyles.
  - **S1 Single-user (#145):** the device token and `POST /device-login`, first run at `/welcome` gated on a one-time grant set by device-login, and the server-era UI hidden in the WebView build.

**Remaining slices, in order:**

| Slice | Issue | Blocked by | Notes |
|---|---|---|---|
| S2a Session play: steps | #146 | — (**ready now**) | Read the "reuse from #152" comment on #146: move the hold-to-repeat code out of `worksets.html`, don't rewrite it. |
| S2b Session play: summary | #147 | #146 | Migration for `session_rpe` and `finished_at`. Use `scripts/new-migration`; never hand-write revisions. |
| S3 Native rest bridge | #148 | #146 | Kotlin. Can run in parallel with S2b. |
| S4 Today + navigation | #149 | #146 | Read the "reuse from #152" comment on #149. |
| S5 Progress | #150 | #149 | |
| S6 Settings + cleanup | #151 | #149, #150 | Also updates the stale CLAUDE.md "Current state". |

Each issue has scope, out-of-scope and acceptance checkboxes. Dependencies are the `Blocked by: #…` line at the top of each issue body.

## How to run it

Use the repo's `/orchestrate` skill (`.claude/skills/orchestrate/SKILL.md`), e.g. `/orchestrate 146`. Once #146 is merged, run `/orchestrate 147 148 149`. S2b and S3 can run in parallel; S4 touches templates both of them touch, so expect small conflicts. Adapt the skill to this environment:

- **No `gh` CLI.** Use the GitHub MCP tools (`mcp__github__*`, loaded via ToolSearch) for issues, PRs, reviews and merging.
- **No `invoke_subagent`.** Use the Agent tool: `general-purpose` with `model: "sonnet"` for implementers, `run_in_background: true`, and one git worktree per ticket under `.worktrees/` (git-ignored). Give each agent a self-contained prompt: the issue scope, its worktree path and branch, "do NOT push/PR/merge", the gates below, and the commit trailer lines.
- **Adversarial review:** the owner skipped the Opus review last time to save session budget. **Ask the owner** whether to run it this time. Otherwise request a Copilot review with `mcp__github__request_copilot_review` and fix every non-low finding test-first. The last Copilot review caught a real security hole (an unauthenticated first-run claim).
- **Push restriction:** the session may only allow pushing to its designated `claude/…` branch. If so, integrate on that branch, restarted from latest `main` if its previous PR was merged, and open the batch PR from it. Never push to `main`.
- **Merge the PR only on the owner's explicit go.** Before merging, confirm that CI on the head is green, the PR is mergeable, and every review thread is resolved.

## Environment gotchas (these cost time last session)

- **Run the gates with the project interpreter first on PATH:** `PATH=/usr/local/bin:$PATH scripts/test`, and the same for `scripts/lint` and `scripts/test-browser`. The `pytest` and `mypy` on the default PATH are isolated uv tools without the project's packages. If the packages are missing, run `pip install -r requirements-dev.txt`.
- **Baseline on `main` after #153:** `scripts/test` 442 passed, `scripts/lint` OK, `scripts/test-browser` 23 passed. Chromium is preinstalled at `/opt/pw-browsers/chromium`; never run `playwright install`.
- **No Android SDK in the container.** Kotlin can't be compiled here, so flag every Kotlin change as uncompiled in the PR. S3 (#148) is mostly Kotlin; have its agent keep the changes minimal and match `MainActivity.kt` and `ServerManager.kt` closely.
- **Rebase a stale branch before merging.** `scripts/pre-merge-check <branch> [base]` flags a branch as stale; rebase it onto the integration branch and rerun the suites first. After integrating two slices, grep for tokens or classes one slice removed and the other still uses. Last time S1's new template used the `--accent` token, which S0 had deleted.
- **If you check visuals with screenshots,** use Playwright with `executable_path="/opt/pw-browsers/chromium"` and a live server like `tests/e2e/conftest.py`'s `live_server`. Also note the glass lesson in V6: a blur over ~4 px turns the thin topo lines into flat black.

## Open items on the owner, not you

- Build the Android app. Neither #153's device sign-in nor its status-bar Kotlin has been compiled.
- Run §9 of `docs/android-smoke-checklist-2026-09-23.md` on the Galaxy S22 Ultra (Android 16), and look at the glass and topo strength on the phone.
- Known cosmetic leftover: the device user's placeholder email `device-owner@griptrack.local` shows in a couple of "Logged in as…" spots. S4 or S6 should drop those.

Start by reading #146 (and its reuse comment) and ADR-0014, check the baseline gates on `main`, then state your wave plan and dispatch.
