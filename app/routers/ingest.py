"""Ingestion triggers + webhooks + collector status (sec 9, NFR-07)."""
from fastapi import APIRouter, Depends, Request
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

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

_ingest = ingest_events  # shared pipeline: webhooks behave exactly like the scheduler

@router.post("/ingest/{source}")
async def ingest(source: str, request: Request, db: Session = Depends(get_db),
                 user=Depends(get_current_user)):
    """Manual trigger + webhook target (PRTG HTTP Action / Zabbix webhook post here)."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    dry = body.get("dry_run", True)
    items = body.get("events") or body.get("sensors") or body.get("problems") or []
    s = source.lower()
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
    except Exception as e:  # noqa: BLE001 — collector errors surface on status page (gap #10)
        record_run(db, source, False, str(e)[:500])
        return JSONResponse({"error": str(e)[:500]}, status_code=500)

@router.get("/collector-status", response_class=HTMLResponse)
def collector_status(request: Request, user=Depends(get_current_user), db: Session = Depends(get_db)):
    from ..models import CollectorRun
    runs = db.query(CollectorRun).all()
    stale = stale_sources(db)
    return templates.TemplateResponse(request, "collector_status.html", { "user": user, "runs": runs, "stale": stale})
