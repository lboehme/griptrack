# Handoff — PWA + reliability shipped; Oracle switch pending account

2026-07-08. Fresh-agent continuation doc. Read `CLAUDE.md` + `CONTEXT.md`
first, plus the previous handoff (`post-guided-max-test-2026-07-07.md`) —
its process gotchas (branch off `origin/main`, merge-then-`scripts/deploy`,
stale-local-`main` trap) all still bind and aren't repeated here.

## Where things stand

Everything queued at session start is shipped and deployed to Fly:

- **PWA Tier 1 complete, PRD #19 closed.** #26 (manifest/icons, PR #39) and
  #27 (service worker, PR #40). Icons are generated, not hand-drawn — rerun
  `scripts/generate-icons` (Pillow, dev-only dep) after any glyph/brand
  change. **Maintenance rule that will bite:** whenever a precached static
  asset changes (`app.css`, `htmx.min.js`, icons), bump `CACHE_VERSION` in
  `backend/routers/pwa.py` or installed clients keep the stale asset.
- **#29 closed (Litestream off-box backup, PR #42).** Replication is baked
  into the image but **inert until five env values exist** (bucket,
  endpoint, region, key id, secret — see `.env.example`). Design details
  and the local disaster-drill method are in PR #42's description.
- **Oracle Always Free deployment path merged untested** (PR #41):
  `deploy/oracle/` + `scripts/oracle-deploy` + `docs/deployment-oracle.md`.
  No OCI VM exists yet, so first real use may need a round of fixes.
- **Canonical domain: `https://griptrack.duckdns.org`** → Fly (A
  66.241.124.190, AAAA 2a09:8280:1::13f:bb10:0; cert issued and verified).
  `griptrack.fly.dev` still works but the DuckDNS name is *the* URL now —
  PWA installs are origin-bound, so the future host switch must be
  DNS-only. Owner controls the DuckDNS account.

## The blocker, and the plan when it clears

**Oracle account signup is stuck** (error at signup; owner has a customer
support ticket open). Everything below waits on it:

1. OCI console: create Object Storage bucket + Customer Secret Key
   (`docs/deployment-oracle.md` §2b — owner-only console work).
2. Enable Litestream on Fly first: `fly secrets set` the five values, deploy,
   confirm "Serving under Litestream replication" in logs, run the restore
   drill from `docs/deployment.md`.
3. Provision the A1.Flex VM (§1), run `deploy/oracle/setup-server`, put the
   same five values in `/opt/griptrack/.env`, `scripts/oracle-deploy` — the
   first boot auto-restores the DB from the bucket (that *is* the data
   migration).
4. Verify on the VM, flip DuckDNS's IP to the VM, scale Fly to zero. Never
   run two writers against one bucket path.

## Also pending

- **Owner hasn't yet phone-tested the PWA** (install from
  griptrack.duckdns.org over https, airplane-mode offline fallback, icon).
  His post-testing UX notes are the usual work queue — expect a batch.
- Open issues: #20 (offline WorkSet sync — needs design/grill first),
  #28 (injury-risk guardian — only after Asymmetry Analytics, which has no
  issue yet; see CLAUDE.md roadmap).

## New this session (not in the previous handoff)

- Session ran as a background job; owner approves gates with terse
  "publish and deploy" turns. Pattern that worked: build → verify → draft
  PR → hold; merge+deploy only on his say-so.
- `scripts/deploy` from a worktree is fine but check
  `git diff HEAD origin/main --stat` is empty first (unchanged rule);
  a `Monitor` on `gh pr checks <n>` is the clean way to wait for CI.
- Uvicorn takes ~8s to boot locally (pandas/matplotlib imports) — use a
  retry loop, not a fixed sleep, before curling a dev server.
- Owner installed the addyosmani/agent-skills pack **user-level for Claude
  Code only** (`~/.claude/skills`). Several overlap this repo's project
  skills — for GripTrack work keep using the project's `tdd`,
  `code-review`, `grilling`; the repo's conventions win.

## Suggested skills

- `tdd` (the project one) — any feature work, e.g. after the owner's PWA
  phone-test feedback lands.
- `grilling` / `domain-modeling` — required before #20 or the Asymmetry
  Analytics → #28 chain; both are explicitly "needs design first".
- `code-review` — per the owner's policy (memory): run it for changes that
  introduce/modify a module boundary; skip for small implementation-only
  builds when he says so.
