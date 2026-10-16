"""Heartbeat — monitoring the monitor (NFR-07)."""
from __future__ import annotations
from sqlalchemy.orm import Session
from ..models import CollectorRun
from ..utils_time import utcnow, ensure_utc

HEARTBEAT_LIMIT_MIN = 15  # alert if no collector run within this

def record_run(db: Session, source: str, ok: bool = True, error: str = "") -> None:
    row = db.get(CollectorRun, source.upper())
    if not row:
        row = CollectorRun(source=source.upper())
        db.add(row)
    row.last_run_at = utcnow()
    row.last_ok = ok
    row.last_error = error or ""
    db.commit()

def stale_sources(db: Session, limit_min: int = HEARTBEAT_LIMIT_MIN) -> list[str]:
    out = []
    now = utcnow()
    for row in db.query(CollectorRun).all():
        if not row.last_run_at:
            out.append(row.source)
            continue
        age = (now - ensure_utc(row.last_run_at)).total_seconds() / 60
        if age > limit_min or not row.last_ok:
            out.append(row.source)
    return out
