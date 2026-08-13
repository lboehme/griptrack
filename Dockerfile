FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# Litestream: continuous off-box SQLite replication (issue #29). The .deb is
# fetched with Python because the slim image has no curl/wget; dpkg handles
# placement. Multi-arch: x86_64 on Fly, arm64 on an Oracle Ampere VM.
ARG LITESTREAM_VERSION=0.5.14
RUN arch="$(dpkg --print-architecture)" \
    && case "$arch" in \
        amd64) ls_arch=x86_64 ;; \
        arm64) ls_arch=arm64 ;; \
        *) echo "unsupported arch: $arch" >&2; exit 1 ;; \
    esac \
    && url="https://github.com/benbjohnson/litestream/releases/download/v${LITESTREAM_VERSION}/litestream-${LITESTREAM_VERSION}-linux-${ls_arch}.deb" \
    && python -c "import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], '/tmp/litestream.deb')" "$url" \
    && dpkg -i /tmp/litestream.deb \
    && rm /tmp/litestream.deb \
    && litestream version

COPY deploy/litestream.yml /etc/litestream.yml

COPY backend/ backend/
COPY migrations/ migrations/
COPY alembic.ini .

# The DB lives on a mounted volume, not the image (see GRIPTRACK_DATABASE_URL).
# entrypoint runs migrations, then serves. --proxy-headers so the app trusts
# the platform's TLS terminator for https cookies and client IPs.
COPY docker-entrypoint.sh .
RUN chmod +x docker-entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
