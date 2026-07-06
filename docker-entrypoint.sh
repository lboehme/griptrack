#!/bin/sh
set -e

# Bring the schema up to date on every boot (seeds grip types + the global
# TrainingProtocol row on a fresh DB via the data migrations).
alembic upgrade head

# --proxy-headers + trusting the platform's forwarded IPs so request.url is
# https (Secure cookies) and request.client.host is the real client (login
# rate limiting), not the reverse proxy.
exec uvicorn backend.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --proxy-headers \
    --forwarded-allow-ips "*"
