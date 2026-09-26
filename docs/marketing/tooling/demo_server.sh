#!/bin/sh
# Build a fresh demo database and serve the on-device (WebView) build of the
# app on it, the way the Android shell does. Run from the repo root:
#   docs/marketing/tooling/demo_server.sh <workdir> [port]
# The capture scripts sign in through /device-login with DEMO_DEVICE_TOKEN.
set -e
WORK="$1"
PORT="${2:-8765}"
TODAY="${DEMO_TODAY:-2026-09-26}"
mkdir -p "$WORK"
rm -f "$WORK"/demo.db "$WORK"/demo.db-*
export GRIPTRACK_DATABASE_URL="sqlite:///$WORK/demo.db"
export PYTHONPATH="$PWD"
alembic upgrade head >/dev/null 2>&1
python3 docs/marketing/tooling/seed_demo.py --today "$TODAY"
export GRIPTRACK_WEBVIEW_BUILD=1
export GRIPTRACK_DEVICE_TOKEN="${DEMO_DEVICE_TOKEN:-demo-device-token}"
exec uvicorn backend.main:app --host 127.0.0.1 --port "$PORT" --log-level warning
