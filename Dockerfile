# ---- Build stage -------------------------------------------------------------
FROM python:3.14-slim@sha256:a7c1e6f3b2d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0 AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv/elnoc

# Install build dependencies for any wheel compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ---- Runtime stage -----------------------------------------------------------
FROM python:3.14-slim@sha256:a7c1e6f3b2d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/home/elnoc/.local/bin:$PATH

WORKDIR /srv/elnoc

# Create non-root user for the app
RUN groupadd -r elnoc && useradd -r -g elnoc -d /home/elnoc -s /sbin/nologin elnoc

# Copy installed packages from builder
COPY --from=builder /root/.local /home/elnoc/.local

# Copy application code
COPY --chown=elnoc:elnoc app ./app
COPY --chown=elnoc:elnoc ELNOC.png ./ELNOC.png

# Never bake secrets: configure entirely through environment (.env file or
# platform env vars). See .env.example and HOSTING.md.
VOLUME ["/srv/elnoc/data", "/srv/elnoc/evidence", "/srv/elnoc/backups"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=8)"

# Run as non-root user
USER elnoc

# Single worker: SQLite allows one writer. Postgres deployments may raise this.
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
