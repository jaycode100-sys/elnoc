"""Shared intake pipeline: every source funnels through here.

Both the 5-minute scheduler (tools/run_collectors.py) and the push webhooks
(POST /ingest/{source}) call ingest_events(), so pull and push behave
identically: maintenance suppression → idempotent store → optical reading
(FR-82) → one-case correlation → instant notify on critical (FR-30).
"""
from __future__ import annotations
from datetime import timedelta
from sqlalchemy.orm import Session
from ..models import Link, Customer, OpticalReading, Event
from ..utils_time import ensure_utc
from .correlation import store_event, correlate_to_case, in_maintenance
from ..notify.dispatcher import notify_case

# A retried poll minutes later must not double-record; the next real poll
# (≥ one interval out) always records — flatlines are signal too.
READING_DEDUP_MIN = 6


def _keep_reading(db: Session, re, link_id: int | None) -> None:
    """FR-82: keep every optical reading per poll. Runs even when the alarm
    fingerprint already exists — the RSL *now* is new information. Compared
    in Python (not SQL) so SQLite naive/aware timestamps can't mismatch."""
    if re.rsl_dbm is None:
        return
    now = ensure_utc(re.occurred_at)
    recent = db.query(OpticalReading).filter(
        OpticalReading.device == re.device,
        OpticalReading.source == re.source).order_by(
        OpticalReading.id.desc()).limit(5).all()
    for r in recent:
        try:
            if abs((now - ensure_utc(r.occurred_at)).total_seconds()) < READING_DEDUP_MIN * 60 \
                    and r.rsl_dbm == re.rsl_dbm:
                return
        except Exception:
            continue
    db.add(OpticalReading(link_id=link_id, device=re.device,
                          rsl_dbm=re.rsl_dbm, occurred_at=re.occurred_at,
                          source=re.source))
    db.commit()


def _would_create(db: Session, re) -> bool:
    """dry_run fingerprint check — no writes (see ingest_events)."""
    from .correlation import fingerprint
    key = fingerprint(re.source, re.device, re.etype,
                      ensure_utc(re.occurred_at or utcnow()),
                      getattr(re, "key_extra", "") or "")
    return db.get(Event, key) is None


def ingest_events(db: Session, raw_events, dry_run: bool = False) -> dict:
    opened, updated, suppressed, notified = 0, 0, 0, 0
    for re in raw_events or []:
        if in_maintenance(db, re.device, None, re.occurred_at):
            suppressed += 1
            continue
        if dry_run:
            # Report what WOULD happen. Never touch the database: a "dry run"
            # that writes events and opens cases is worse than no flag at all.
            if _would_create(db, re):
                opened += 1
            else:
                updated += 1
            continue
        ev, created = store_event(db, re.source, re.etype, re.device, re.summary,
                                  re.severity, re.occurred_at, re.ref, re.raw,
                                  key_extra=getattr(re, "key_extra", "") or "")
        # Reading first: kept even for duplicate alarms (see _keep_reading).
        _keep_reading(db, re, ev.link_id)
        if not created and ev.case_id:
            updated += 1
            continue
        case = correlate_to_case(db, ev)
        if case and created:
            opened += 1
            # instant for critical (FR-30); the rest ride the digest + dashboard
            if (ev.severity or "").lower() == "critical" and not dry_run:
                link = db.get(Link, case.link_id) if case.link_id else None
                cust = db.get(Customer, case.customer_id) if case.customer_id else None
                aff = f"{cust.name if cust else ''} {link.name if link else re.device}".strip()
                notify_case(db, case, ev.summary, aff, dry_run=False)
                notified += 1
        elif case:
            updated += 1
    return {"opened": opened, "updated": updated,
            "suppressed": suppressed, "notified": notified}
