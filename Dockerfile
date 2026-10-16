FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv/elnoc

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Server code + brand asset served at /logo.png and /favicon.ico.
COPY app ./app
COPY ELNOC.png ./ELNOC.png

# Never bake secrets: configure entirely through environment (.env file or
# platform env vars). See .env.example and HOSTING.md.
VOLUME ["/srv/elnoc/data", "/srv/elnoc/evidence", "/srv/elnoc/backups"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=8)"

# Single worker: SQLite allows one writer. Postgres deployments may raise this.
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
