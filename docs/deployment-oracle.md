# Deploying GripTrack to Oracle Cloud Always Free Tier

Companion to `docs/deployment.md` (the host-agnostic guide — read it first;
everything there about env vars, the bootstrap token, migrations-on-boot,
and backups applies unchanged). This walkthrough covers the Oracle-specific
pieces: provisioning the VM, the two firewalls, and the two scripts that do
the rest.

**Shape:** one always-free VM runs the app container plus a Caddy container
(`deploy/oracle/compose.yaml`). Caddy terminates TLS with an automatic
Let's Encrypt certificate — required, because the production session cookie
is `Secure` and login simply won't persist over plain HTTP. Unlike Fly
there's no auto-stop/auto-start: the VM runs continuously, so there's no
cold-start wake and no usage-based billing to think about.

The pieces:

| What | Where | Runs |
|---|---|---|
| `deploy/oracle/setup-server` | copied to the VM | once, as root |
| `scripts/oracle-deploy` | your machine | every deploy |
| `deploy/oracle/compose.yaml` + `Caddyfile` | shipped with the source | via the deploy script |

## 1. Provision the VM (console, one time)

In the [Oracle Cloud console](https://cloud.oracle.com), Compute → Instances
→ Create instance:

- **Image:** Ubuntu 24.04 (Minimal is fine).
- **Shape:** `VM.Standard.A1.Flex` (Ampere ARM) — 2 OCPUs / 12 GB is plenty
  and stays well inside the always-free allowance (4 OCPUs / 24 GB total).
  If ARM capacity is exhausted in your region ("Out of capacity" error —
  common), retry later, try another availability domain, or fall back to
  the always-free AMD shape `VM.Standard.E2.1.Micro` (1 GB — still enough
  for this app). The container build is architecture-agnostic either way,
  since the image is built on the VM itself.
- **Networking:** accept the default VCN with a public subnet; make sure
  "Assign a public IPv4 address" is on.
- **SSH key:** add your public key.

Then open the **cloud firewall** (this is separate from the firewall on the
VM itself): VCN → your subnet's **security list** → Add ingress rules:

- source `0.0.0.0/0`, TCP, destination port `80`
- source `0.0.0.0/0`, TCP, destination port `443`
- source `0.0.0.0/0`, UDP, destination port `443` (optional — HTTP/3)

SSH (22) is already open by default. Note the instance's public IP.

## 2. Point a domain at it (one time)

Caddy needs a domain to get a certificate for — an IP alone won't do. Either:

- **Own domain:** add an `A` record for e.g. `griptrack.example.com` → the
  VM's public IP.
- **No domain:** create a free subdomain at [DuckDNS](https://www.duckdns.org)
  (`<name>.duckdns.org`) pointing at the IP. Works fine with Let's Encrypt.

Oracle's public IP survives instance reboots (it's only released if you
terminate the instance), so this is genuinely one-time.

## 2b. Create the backup bucket (one time, strongly recommended)

The container runs Litestream for continuous off-box backup (see the
"Backups" section of `docs/deployment.md`). Oracle Object Storage's
always-free 20 GB is plenty. In the console:

1. **Object Storage → Buckets → Create bucket** — name it e.g.
   `griptrack-backup`, leave it private (default). Note your **namespace**
   (shown on the bucket page, or Tenancy details).
2. **Your user icon → My profile → Customer secret keys → Generate key** —
   this is OCI's name for S3-compatible credentials. Save the access key
   and the secret (the secret is shown once).
3. Fill the backup block in `/opt/griptrack/.env` (setup-server writes the
   placeholders):

   ```sh
   GRIPTRACK_REPLICA_BUCKET=griptrack-backup
   GRIPTRACK_REPLICA_ENDPOINT=https://<namespace>.compat.objectstorage.<region>.oraclecloud.com
   GRIPTRACK_REPLICA_REGION=<region>            # e.g. eu-frankfurt-1
   LITESTREAM_ACCESS_KEY_ID=<access key>
   LITESTREAM_SECRET_ACCESS_KEY=<secret>
   ```

The next deploy picks it up; `docker compose logs app` should show
"Serving under Litestream replication." Run the restore drill from
`docs/deployment.md` once to prove the backup is real.

## 3. Prepare the server (one time)

```sh
scp deploy/oracle/setup-server ubuntu@<vm-ip>:
ssh ubuntu@<vm-ip> sudo ./setup-server <your-domain>
```

This installs Docker + Compose, opens 80/443 in the **instance firewall**
(Oracle's Ubuntu images ship iptables rules that reject everything but SSH —
the security list above is necessary but not sufficient; both layers must
allow the traffic), creates `/opt/griptrack/{src,data}`, and writes
`/opt/griptrack/.env` with a generated session secret and bootstrap token.
**It prints the bootstrap token — save it**; it's the invite code for the
first registration. Re-running is safe: an existing `.env` is never
overwritten.

Reconnect SSH once afterwards so your user's `docker` group membership takes
effect.

### Migrating existing data from Fly (optional, before first deploy)

**Preferred path — through the backup bucket.** Enable Litestream on the
Fly deployment first (`fly secrets set GRIPTRACK_REPLICA_BUCKET=...` etc.,
same five values as section 2b) and let it replicate. Then put the same
five values in `/opt/griptrack/.env` on the VM. On the first
`oracle-deploy`, the entrypoint finds an empty volume and **auto-restores
the database from the replica** before starting. Once you've verified the
Oracle side, scale the Fly app to zero — two live writers replicating into
one bucket path is the situation to avoid, not a merge.

**Alternative — copy the file directly**, with the Fly app not running
(never copy under a live writer; see the backup notes in
`docs/deployment.md`):

```sh
fly ssh sftp get /data/griptrack.db ./griptrack.db --app griptrack
scp ./griptrack.db ubuntu@<vm-ip>:/tmp/griptrack.db
ssh ubuntu@<vm-ip> sudo mv /tmp/griptrack.db /opt/griptrack/data/griptrack.db
rm ./griptrack.db  # don't leave a production DB on your laptop
```

Either way the entrypoint detects the schema is already at head and skips
migration. With existing users, also blank `GRIPTRACK_BOOTSTRAP_TOKEN` in
`/opt/griptrack/.env` — the first-registration window it guards doesn't
exist anymore.

## 4. Deploy (every time)

```sh
scripts/oracle-deploy ubuntu@<vm-ip>     # or set GRIPTRACK_ORACLE_HOST
```

Ships the committed tree (`git archive HEAD` — uncommitted changes don't
deploy, and it warns if HEAD differs from `origin/main`), builds the image
on the VM, restarts the containers, then verifies exactly like
`scripts/deploy` does for Fly: a healthy `https://<domain>/health` (with
retries on the first deploy while Caddy obtains the certificate) plus the
entrypoint's migration/backup log lines. Deploys after the first one reuse
Docker layer caches, so they're quick.

## 5. First registration

As in `docs/deployment.md`: register at `https://<domain>/register` using
the bootstrap token as the invite code — that account becomes admin. Then
blank `GRIPTRACK_BOOTSTRAP_TOKEN=` in `/opt/griptrack/.env` on the VM and
re-run `scripts/oracle-deploy` (or `docker compose ... up -d` on the VM) so
the container picks up the change.

## Backups

Unchanged from `docs/deployment.md`: pre-migration `.bak` files land next to
the DB in `/opt/griptrack/data/`, and a real off-box backup is still on you
(issue #29 tracks the app-consistent hardening). The bind mount makes it
plain file access:

```sh
ssh ubuntu@<vm-ip> "sudo docker compose -f /opt/griptrack/src/deploy/oracle/compose.yaml \
    --env-file /opt/griptrack/.env exec app \
    python -c \"import sqlite3; sqlite3.connect('/data/griptrack.db').backup(sqlite3.connect('/data/backup-latest.db'))\""
scp ubuntu@<vm-ip>:/opt/griptrack/data/backup-latest.db ./griptrack-backup-$(date +%F).db
```

## Troubleshooting

- **Browser can't connect at all** → one of the two firewalls: re-check the
  VCN security-list ingress rules *and* `sudo iptables -L INPUT -n` on the
  VM (80/443 ACCEPT rules must sit above the REJECT line).
- **Certificate errors on first deploy** → DNS not propagated yet, or port
  80 blocked (Let's Encrypt's HTTP challenge needs it). `docker compose
  logs caddy` on the VM shows the ACME attempts.
- **Login doesn't persist** → you're hitting the app over plain HTTP or by
  raw IP; the `Secure` cookie only travels over `https://<domain>`.
