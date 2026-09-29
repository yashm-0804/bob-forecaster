# Serves the operator console and API over precomputed runs.
# Build context is this directory; see DEPLOY.md.
# Pinned by digest (the multi-arch index for python:3.12-slim, 2026-09-27), so
# a rebuild uses the same base. Update deliberately: look up the new digest
# and change it here.
FROM python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # Cloud Run's filesystem is writable only under /tmp, and not durable.
    BOB_AUDIT_DB=/tmp/audit.sqlite3 \
    BOB_TELEMETRY_DB=/tmp/telemetry.sqlite3 \
    # This image listens on every interface: without access codes it refuses
    # writes wherever it runs, not only on Cloud Run.
    BOB_REQUIRE_TOKENS=1

WORKDIR /app
# Every package, transitive ones included, pinned and hash-checked.
COPY requirements-serve.lock .
RUN pip install --no-cache-dir --require-hashes -r requirements-serve.lock

# Only what serving touches. The modelling code stays out of the image.
COPY api/ api/
COPY common/ common/
COPY telemetry/ telemetry/
COPY web/ web/
COPY data/runs/ data/runs/
COPY data/telemetry/*.json data/telemetry/

RUN useradd --create-home app && chown -R app /app
USER app

# Cloud Run sets $PORT; default to 8080 elsewhere.
# --no-proxy-headers: the address the limits count is the connection's, never
# an X-Forwarded-For header, which any caller can write (see DEPLOY.md).
CMD ["sh", "-c", "exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8080} --no-proxy-headers"]
