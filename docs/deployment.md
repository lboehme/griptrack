# Deploying GripTrack

Host-agnostic guide. The app is a single stateless process plus one SQLite
file on a persistent disk. Any host that can run a container (or a Python
process) with a mounted volume works — Fly.io, Railway, Render, a small VPS.
Avoid pure-serverless/edge hosts: SQLite needs a real persistent filesystem,
not ephemeral or read-only storage.

Host-specific walkthroughs: Fly.io is the current production host
(`fly.toml` + `scripts/deploy`); for Oracle Cloud Always Free Tier see
`docs/deployment-oracle.md` (`deploy/oracle/` + `scripts/oracle-deploy`).

## What the container does

`Dockerfile` + `docker-entrypoint.sh` build a Python 3.12 image that, on every
boot, runs `alembic upgrade head` (creating the schema and seeding grip types
+ the global training protocol on a fresh DB) and then serves with uvicorn
behind `--proxy-headers` (so the platform's TLS terminator is trusted for
HTTPS-only cookies and real client IPs).

## Required configuration

Set these as the platform's environment variables / secrets (see
`.env.example`):

| Variable | Required | Purpose |
|---|---|---|
| `GRIPTRACK_ENV=production` | yes | Enables Secure/HTTPS-only session cookies; makes a missing secret a hard startup error. |
| `GRIPTRACK_SESSION_SECRET` | yes | Signs the session cookie. Long random string: `python -c "import secrets; print(secrets.token_urlsafe(48))"`. The app refuses to start in production without it. |
| `GRIPTRACK_DATABASE_URL` | yes | Path to the SQLite file **on the persistent volume**, e.g. `sqlite:////data/griptrack.db`. If this points at the container filesystem, all data is lost on redeploy. |
| `GRIPTRACK_BOOTSTRAP_TOKEN` | strongly recommended | Gates the first-admin registration (see below). |
| `GRIPTRACK_REPLICA_BUCKET` + `GRIPTRACK_REPLICA_ENDPOINT` + `GRIPTRACK_REPLICA_REGION` + `LITESTREAM_ACCESS_KEY_ID` + `LITESTREAM_SECRET_ACCESS_KEY` | strongly recommended | Continuous off-box backup via Litestream (see "Backups"). Setting the bucket switches replication on; all five belong together. |

## Deploy checklist

1. **Provision a persistent volume** and mount it (e.g. at `/data`). Point
   `GRIPTRACK_DATABASE_URL` at a file on it.
2. **Set all required env vars**, including a freshly generated
   `GRIPTRACK_SESSION_SECRET` and a random `GRIPTRACK_BOOTSTRAP_TOKEN`.
3. **Ensure the platform terminates TLS** (HTTPS) in front of the app. The
   Secure session cookie will not be sent over plain HTTP, so login won't
   persist without HTTPS.
4. **Deploy.** The entrypoint migrates and starts the server.
5. **Register yourself immediately**, using the `GRIPTRACK_BOOTSTRAP_TOKEN`
   value as the invite code on the registration form. This first account
   becomes the admin.
6. **Remove `GRIPTRACK_BOOTSTRAP_TOKEN`** (and redeploy/restart). From now on
   registration is invite-only through your admin account.
7. **Invite friends** from your profile page; share each one-time code.

## Why the bootstrap token matters

The first account ever registered becomes admin and needs no invite (it has to
— there's no one to invite it). On a public URL, that means whoever hits
`/register` first claims admin. `GRIPTRACK_BOOTSTRAP_TOKEN` closes that window:
while it's set, even the first registration must present it. Set it before the
first deploy, register, then remove it.

## Migrations on boot

`docker-entrypoint.sh` runs schema migrations before starting the server, but
guards the risky moment (the first boot after a schema-changing deploy):

- It **only migrates when a revision is actually pending** — an idle-wake boot
  with the schema already at head is a no-op, not a blind `alembic upgrade head`.
- Before migrating a populated DB it writes an **app-consistent pre-migration
  backup** next to the DB file, named `griptrack.db.pre-<revision>.bak`, using
  SQLite's online-backup API. The name is keyed to the pre-migration revision
  and never overwritten, so a crash-looping bad migration can't replace the
  clean snapshot; the 10 most recent are retained. If a migration fails, restore
  by copying that `.bak` back over `griptrack.db`.
- A failed migration **stops the boot** (the container exits rather than serving
  the app against a half-migrated schema) — so a bad migration shows up as an
  outage/failed health check, not silent data errors.
- `GRIPTRACK_MIGRATE_ONLY=1` runs the migration step and exits without starting
  the server — handy for applying a migration manually.

**Test each new migration against a copy of the production DB**, not just a
fresh local one — SQLite's batch/table-rebuild migrations can pass on an empty
schema and fail on real data.

## Backups

Three layers, from first line of defense to last resort:

1. **Litestream replication (the real backup — enable it).** When
   `GRIPTRACK_REPLICA_BUCKET` (+ endpoint, region, credentials) is set, the
   container continuously replicates the SQLite WAL to S3-compatible object
   storage and can restore to seconds before a failure. On boot with an
   empty volume it **auto-restores from the replica first** — which makes it
   double as the host-migration mechanism: point the new host at the same
   bucket and boot. Litestream supervises the server process, so a
   misconfigured replica fails the boot loudly rather than silently running
   unprotected. Config template: `deploy/litestream.yml` (baked into the
   image); values come from the env vars in `.env.example`. On Fly, set them
   with `fly secrets set ...`; on the Oracle VM, in `/opt/griptrack/.env`.

   **Run a restore drill before trusting it** (and occasionally after):

   ```sh
   litestream restore -config deploy/litestream.yml -o /tmp/drill.db "$GRIPTRACK_DB_PATH"
   sqlite3 /tmp/drill.db "PRAGMA integrity_check; SELECT count(*) FROM users;"
   ```

2. **Pre-migration `.bak` files** (automatic, on-box): written by the
   entrypoint before any pending migration runs — a safety net for the
   migration path only; they live on the same volume as the DB.

3. **Platform volume snapshots** (Fly: automatic daily, ~5-day retention;
   Oracle: boot-volume backups configurable in the console): block-level and
   not SQLite-consistent — a last resort, not a substitute for layer 1.

Without Litestream enabled, at minimum run a manual app-consistent copy off
the volume now and then: `sqlite3 /data/griptrack.db ".backup '/data/backup-$(date +%F).db'"`
and download it (`.backup`/`VACUUM INTO`, never a raw `cp` of a live file).

## Security posture (what's already handled)

- **Auth:** invite-only registration; bcrypt password hashing; passwords
  8–72 chars; server-side signed session cookie, `HttpOnly` + `SameSite=Lax`,
  and `Secure` in production.
- **CSRF:** `SameSite=Lax` cookie plus an Origin-header check that rejects
  cross-origin POSTs.
- **Brute force:** failed logins are rate-limited per client IP (10 / minute).
  Login timing is equalized so a missing email can't be distinguished from a
  wrong password.
- **Headers:** `Content-Security-Policy` (same-origin; images allow `data:`),
  `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`,
  `Referrer-Policy`.
- **Injection:** all DB access is parameterized via SQLModel; all template
  output is auto-escaped (no raw/`|safe` interpolation).
- **Input bounds:** every numeric field is capped so absurd values can't
  become a CPU/memory DoS (notably the plate subset-sum).
- **Per-user isolation:** every query is scoped to the session user; covered
  by data-isolation tests.

### Known residual trade-off

The CSP allows `'unsafe-inline'` for scripts, because a few small inline
handlers drive the autosave UX. Given full output-escaping and no untrusted
HTML sink, the practical XSS risk is low. Tightening this (externalize the
inline JS, drop `'unsafe-inline'`) is a clean future hardening step if the
audience grows beyond invited friends.

## Running it as a plain process (no Docker)

```sh
pip install -r requirements.txt
export GRIPTRACK_ENV=production
export GRIPTRACK_SESSION_SECRET=...           # generated
export GRIPTRACK_DATABASE_URL=sqlite:////data/griptrack.db
export GRIPTRACK_BOOTSTRAP_TOKEN=...          # for first registration
alembic upgrade head
uvicorn backend.main:app --host 0.0.0.0 --port 8000 \
    --proxy-headers --forwarded-allow-ips "*"
```

Put it behind a TLS-terminating reverse proxy (Caddy/nginx/Cloudflare).
