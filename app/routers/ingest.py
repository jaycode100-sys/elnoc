"""Ingestion triggers + webhooks + collector status (sec 9, NFR-07).

Webhook endpoints (PRTG HTTP Action, Zabbix webhook, etc.) are authenticated
via a per-source shared secret sent in the `X-Webhook-Secret` header.
Browser session cookies are NOT required — external monitoring systems cannot
use them.

Rate limited: 30 requests per minute per source.
"""
from __future__ import annotations

import time
from collections import defaultdict
from fastapi import APIRouter, Depends, Request, Header
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path
from ..database import get_db
from ..security import get_current_user
from ..adapters import prtg, zabbix, smartolt, mailbox
from ..services.ingestion import ingest_events
from ..services.heartbeat import record_run, stale_sources
from ..services.escalation import due_for_next_step, steps_for_case
from ..notify.dispatcher import notify_case
from ..models import Link, Customer
from ..utils_time import utcnow
from ..config import settings

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

_ingest = ingest_events  # shared pipeline: webhooks behave exactly like the scheduler

# Per-source webhook secrets from env: ELNOC_WEBHOOK_SECRET_PRTG, etc.
def _webhook_secret(source: str) -> str | None:
    return os.environ.get(f"ELNOC_WEBHOOK_SECRET_{source.upper()}")

import os

# Rate limiting: 30 requests per minute per source
_WEBHOOK_ATTEMPTS: dict[tuple[str, str], list[float]] = defaultdict(list)
_WEBHOOK_RATE_LIMIT = 30
_WEBHOOK_RATE_WINDOW = 60


def _check_webhook_rate(identifier: str) -> bool:
    now = time.time()
    key = ("webhook", identifier)
    attempts = [t for t in _WEBHOOK_ATTEMPTS[key] if now - t < _WEBHOOK_RATE_WINDOW]
    _WEBHOOK_ATTEMPTS[key] = attempts
    if len(attempts) >= _WEBHOOK_RATE_LIMIT:
        return False
    attempts.append(now)
    return True


def _verify_webhook(source: str, secret_header: str | None) -> bool:
    expected = _webhook_secret(source)
    if not expected:
        # No secret configured for this source — reject all webhook calls
        return False
    if not secret_header:
        return False
    import hmac
    return hmac.compare_digest(secret_header, expected)


@router.post("/ingest/{source}")
async def ingest(source: str, request: Request, x_webhook_secret: str | None = Header(None),
                 db: Session = Depends(get_db)):
    """Manual trigger + webhook target (PRTG HTTP Action / Zabbix webhook post here).

    Authentication: per-source shared secret in `X-Webhook-Secret` header.
    No browser session cookie required.
    Rate limit: 30 requests/minute per source.
    """
    s = source.lower()
    if s not in ("prtg", "zabbix", "smartolt", "mailbox"):
        return JSONResponse({"error": "unknown source"}, status_code=404)

    # Rate limit
    client_host = request.client.host if request.client else "unknown"
    if not _check_webhook_rate(f"{client_host}:{s}"):
        return JSONResponse({"error": "webhook rate limit exceeded"}, status_code=429)

    # Webhook secret auth
    if not _verify_webhook(s, x_webhook_secret):
        return JSONResponse({"error": "webhook secret required or invalid"}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        body = {}
    dry = body.get("dry_run", False)
    items = body.get("events") or body.get("sensors") or body.get("problems") or []
    if s == "prtg":
        raw = prtg.collect_prtg(fetcher=(lambda: items) if items else None)
    elif s == "zabbix":
        raw = zabbix.collect_zabbix(fetcher=(lambda: items) if items else None)
    elif s == "smartolt":
        raw = smartolt.collect_smartolt(fetcher=(lambda: items) if items else None)
    elif s == "mailbox":
        raw = mailbox.collect_mailbox(fetcher=(lambda: items) if items else None)
    else:
        return JSONResponse({"error": "unknown source"}, status_code=404)
    try:
        res = _ingest(db, raw, dry_run=dry)
        record_run(db, source, True)
        res["source"] = source
        return JSONResponse(res)
    except Exception as e:  # noqa: BLE001 — collector errors surface on status page
        record_run(db, source, False, str(e)[:500])
        return JSONResponse({"error": str(e)[:500]}, status_code=500)


@router.get("/collector-status", response_class=HTMLResponse)
def collector_status(request: Request, user=Depends(get_current_user), db: Session = Depends(get_db)):
    from ..models import CollectorRun
    runs = db.query(CollectorRun).all()
    stale = stale_sources(db)
    return templates.TemplateResponse(request, "collector_status.html", { "user": user, "runs": runs, "stale": stale})
