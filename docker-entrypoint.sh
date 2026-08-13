#!/bin/sh
set -e

# ---------------------------------------------------------------------------
# Schema migration on boot — hardened.
#
# `alembic upgrade head` is idempotent, so an idle-wake boot with the schema
# already current is a no-op. The real risk is the *first* boot after a
# schema-changing deploy: a migration that misbehaves against the real volume
# DB (SQLite's limited ALTER forces batch/table-rebuild migrations) could
# corrupt or half-apply the single database file. So before migrating we:
#   1. only act when a migration is actually pending (else skip entirely),
#   2. take an app-consistent backup of the SQLite file, keyed by the current
#      (pre-migration) revision and never overwritten — so a crash-loop can't
#      replace the clean snapshot with an already-suspect one,
#   3. fail loudly (set -e) rather than serve the app on a half-migrated DB.
#
# The pre-migration .bak files live on the volume next to the DB and are a
# last-ditch, on-box safety net — complementary to Fly's volume snapshots,
# not a replacement for an off-box backup (see docs/deployment.md).
#
# Set GRIPTRACK_MIGRATE_ONLY=1 to run this migration block and exit without
# starting the server (used by the migration smoke-test, and handy for
# running migrations manually).
# ---------------------------------------------------------------------------

# Resolve the SQLite file path with the same precedence as backend/db.py.
DB_URL="${GRIPTRACK_DATABASE_URL:-${DATABASE_URL:-sqlite:///./griptrack.db}}"
case "$DB_URL" in
    sqlite:*) DB_PATH=$(printf '%s' "$DB_URL" | sed 's|^sqlite:///||') ;;
    *)        DB_PATH="" ;;  # non-SQLite backend: no file to back up
esac

# ---------------------------------------------------------------------------
# Off-box replication (issue #29). When GRIPTRACK_REPLICA_BUCKET is set,
# Litestream continuously replicates the SQLite file to S3-compatible object
# storage (config: /etc/litestream.yml, values env-expanded) and supervises
# the server process. Without it, this container behaves exactly as before.
#
# The restore step must run BEFORE the migration block: on a fresh volume
# (host switch, volume loss) the DB is pulled back from the replica; if
# alembic ran first it would build an empty schema, and replicating that
# empty DB would bury the real data under a newer generation.
# ---------------------------------------------------------------------------
LITESTREAM_CONFIG="${LITESTREAM_CONFIG:-/etc/litestream.yml}"
replicate=""
if [ -n "${GRIPTRACK_REPLICA_BUCKET:-}" ] && [ -n "$DB_PATH" ]; then
    replicate=1
    export GRIPTRACK_DB_PATH="$DB_PATH"  # referenced by the litestream config
    if [ ! -f "$DB_PATH" ]; then
        echo "[entrypoint] No local DB; restoring from replica if one exists..."
        litestream restore -config "$LITESTREAM_CONFIG" \
            -if-db-not-exists -if-replica-exists "$DB_PATH"
    fi
fi

current_line=$(alembic current 2>/dev/null || true)
current_rev=$(printf '%s' "$current_line" | awk 'NR==1 {print $1}')

if printf '%s' "$current_line" | grep -q '(head)'; then
    echo "[entrypoint] Schema already at head (${current_rev}); skipping migration."
else
    echo "[entrypoint] Pending schema migration (current: ${current_rev:-none})."

    # Back up only when there's an existing, non-empty DB to protect. A fresh
    # DB (no current revision / empty file) has nothing to lose.
    if [ -n "$current_rev" ] && [ -n "$DB_PATH" ] && [ -s "$DB_PATH" ]; then
        backup="${DB_PATH}.pre-${current_rev}.bak"
        if [ -f "$backup" ]; then
            echo "[entrypoint] Pre-migration backup already exists (${backup}); preserving it."
        else
            echo "[entrypoint] Backing up ${DB_PATH} -> ${backup}"
            # Online-backup API: consistent even with a concurrent/WAL DB.
            python - "$DB_PATH" "$backup" <<'PY'
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
source = sqlite3.connect(src)
dest = sqlite3.connect(dst)
with dest:
    source.backup(dest)
dest.close()
source.close()
PY
            # Retain the 10 most recent pre-migration backups.
            ls -1t "${DB_PATH}".pre-*.bak 2>/dev/null | tail -n +11 | while read -r old; do
                echo "[entrypoint] Pruning old backup ${old}"
                rm -f "$old"
            done
        fi
    else
        echo "[entrypoint] Fresh/empty database; no pre-migration backup needed."
    fi

    echo "[entrypoint] Running alembic upgrade head..."
    alembic upgrade head
    echo "[entrypoint] Migration complete."
fi

if [ "${GRIPTRACK_MIGRATE_ONLY:-}" = "1" ]; then
    echo "[entrypoint] GRIPTRACK_MIGRATE_ONLY set; not starting server."
    exit 0
fi

# --proxy-headers + trusting the platform's forwarded IPs so request.url is
# https (Secure cookies) and request.client.host is the real client (login
# rate limiting), not the reverse proxy.
#
# --loop asyncio --http h11: uvicorn's own defaults ("auto") would already
# fall back to these since requirements.txt no longer pins uvloop/httptools
# (#94, ahead of the Android/Chaquopy build in #93, which wants the smallest
# native-wheel surface). Pinning them explicitly makes that intentional
# rather than incidental — the plain runner keeps serving correctly even if
# a future transitive dependency happens to pull uvloop/httptools back in.
SERVE="uvicorn backend.main:app \
    --host 0.0.0.0 \
    --port ${PORT:-8000} \
    --proxy-headers \
    --forwarded-allow-ips * \
    --loop asyncio \
    --http h11"

if [ -n "$replicate" ]; then
    # Litestream supervises the server: replication runs for exactly as long
    # as the app does, and a misconfigured replica fails the boot loudly
    # instead of silently running without backups.
    echo "[entrypoint] Serving under Litestream replication."
    exec litestream replicate -config "$LITESTREAM_CONFIG" -exec "$SERVE"
fi
# set -f: $SERVE must word-split but its literal * must not glob-expand.
set -f
exec $SERVE
