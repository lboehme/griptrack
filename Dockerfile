FROM python:3.12-slim

# matplotlib needs a writable, non-interactive config dir and no GUI backend.
ENV MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/mpl \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

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
