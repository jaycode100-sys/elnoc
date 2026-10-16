"""Event -> case correlation (FR-06..FR-09). Stable fingerprint, idempotent store."""
from __future__ import annotations
import hashlib
from datetime import timedelta
from sqlalchemy.orm import Session
from ..models import Event, Case, CaseEvent, Link, SiteDevice, MaintenanceWindow
from ..utils_time import utcnow, ensure_utc
from ..config import settings

def fingerprint(source: str, device: str, etype: str, occurred_at,
                key_extra: str = "") -> str:
    """Stable fingerprint — never uses 'now' (fixes gap #1). key_extra keeps
    same-day/same-device items distinct when the source needs it (mailbox
    subjects); PRTG/Zabbix leave it empty so repeats still collapse."""
    day = ensure_utc(occurred_at).strftime("%Y-%m-%d")
    base = f"{source.strip().upper()}|{device.strip().lower()}|{etype.strip().lower()}|{day}"
    if (key_extra or "").strip():
        base += f"|{key_extra.strip().lower()}"
    return hashlib.sha256(base.encode()).hexdigest()[:32]

def in_maintenance(db: Session, device: str, link_id: int | None, at) -> bool:
    at = ensure_utc(at)
    q = db.query(MaintenanceWindow).filter(
        MaintenanceWindow.start <= at, MaintenanceWindow.end >= at).all()
    for w in q:
        if w.target_type == "device" and w.target.lower() == (device or "").lower():
            return True
        if w.target_type == "link" and link_id and str(w.target) == str(link_id):
            return True
    return False

def resolve_link(db: Session, device: str) -> Link | None:
    if not device:
        return None
    # 1) site_device mapping
    sd = db.query(SiteDevice).filter(SiteDevice.hostname.ilike(device.strip())).first()
    if sd and sd.link_id:
        return db.get(Link, sd.link_id)
    # 2) link name / alias contains device
    dev = device.strip().lower()
    for l in db.query(Link).all():
        blob = f"{l.name} {l.aliases or ''} {l.a_end or ''} {l.b_end or ''}".lower()
        if dev and dev in blob:
            return l
    return None

def store_event(db: Session, source: str, etype: str, device: str, summary: str,
                severity: str, occurred_at, ref: str = "", raw: str = "",
                link_id: int | None = None, key_extra: str = "") -> tuple[Event, bool]:
    """Returns (event, created). Idempotent: same key never stored twice (NFR-08)."""
    occurred_at = ensure_utc(occurred_at or utcnow())
    key = fingerprint(source, device, etype, occurred_at, key_extra)
    existing = db.get(Event, key)
    if existing:
        return existing, False
    if link_id is None:
        link = resolve_link(db, device)
        link_id = link.id if link else None
    ev = Event(key=key, type=etype, source=source.upper(), device=device,
               summary=summary, severity=severity, ref=ref or "",
               occurred_at=occurred_at, received_at=utcnow(),
               link_id=link_id, raw=raw or "")
    db.add(ev)
    db.commit()
    return ev, True

def correlate_to_case(db: Session, ev: Event, engineer: str = "auto") -> Case | None:
    """Same link/device within window -> one case (FR-07). Recovery -> note (FR-08)."""
    window = timedelta(minutes=settings.CORRELATION_WINDOW_MIN)
    now = utcnow()
    link_id = ev.link_id
    # find open case on same link or device
    q = db.query(Case).filter(Case.status != "resolved")
    if link_id:
        q = q.filter(Case.link_id == link_id)
    elif ev.device:
        q = q.filter(Case.device.ilike(ev.device.strip()))
    candidates = q.order_by(Case.opened_at.desc()).all()
    # within time window
    open_case = None
    for c in candidates:
        last = c.last_escalation_at or c.opened_at
        if ensure_utc(now) - ensure_utc(c.opened_at) <= window or ensure_utc(now) - ensure_utc(last) <= window:
            open_case = c
            break
    if not open_case and candidates and link_id:
        # same link, still open -> reuse (prevents flood, gap #6)
        open_case = candidates[0]

    is_recovery = ev.type.lower() in ("up", "recovery", "resolve", "ok", "clear")
    if is_recovery:
        if open_case:
            db.add(CaseEvent(case_id=open_case.id, at=now, engineer="system",
                             kind="system",
                             text=f"Recovery seen ({ev.source}: {ev.summary}). Consider closing — human must close (FR-08)."))
            ev.case_id = open_case.id
            if (open_case.link_state or "").lower() != "up":
                open_case.link_state = "up"
            db.commit()
        return open_case

    if open_case:
        db.add(CaseEvent(case_id=open_case.id, at=now, engineer="system", kind="system",
                         text=f"Update from {ev.source}: {ev.summary} [{ev.device}]"))
        ev.case_id = open_case.id
        db.commit()
        return open_case

    # open new case stub
    link = db.get(Link, link_id) if link_id else resolve_link(db, ev.device)
    sev = ev.severity or "major"
    case = Case(
        engineer=engineer, opened_by="auto",
        customer_id=link.customer_id if link else None,
        link_id=link.id if link else None,
        device=ev.device or "",
        symptom=f"{ev.source}: {ev.summary}",
        severity=sev, status="open",
        link_state="down" if sev == "critical" else "degraded",
        waiting_on="",
    )
    db.add(case)
    db.flush()
    db.add(CaseEvent(case_id=case.id, at=now, engineer="system", kind="system",
                     text=f"Auto-opened from {ev.source} event {ev.key[:8]}: {ev.summary}"))
    ev.case_id = case.id
    db.commit()
    return case
