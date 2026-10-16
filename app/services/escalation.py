"""Escalation engine (FR-26..FR-30) + delivery-rule defaults (sec 10.2)."""
from __future__ import annotations
import secrets
from sqlalchemy.orm import Session
from ..models import Case, Contact, Link, EscalationRule, Notification, CaseEvent, CaseWatcher
from ..utils_time import utcnow, ensure_utc, age_minutes
from ..config import settings

def steps_for_case(db: Session, case: Case) -> list[EscalationRule]:
    if case.link_id:
        rules = db.query(EscalationRule).filter(
            EscalationRule.link_id == case.link_id).order_by(EscalationRule.step_order).all()
        if rules:
            return rules
    if case.customer_id:
        return db.query(EscalationRule).filter(
            EscalationRule.customer_id == case.customer_id).order_by(EscalationRule.step_order).all()
    return []

def primary_contact(db: Session, case: Case) -> Contact | None:
    if case.link_id:
        link = db.get(Link, case.link_id)
        if link and link.primary_contact_id:
            return db.get(Contact, link.primary_contact_id)
    steps = steps_for_case(db, case)
    if steps:
        return db.get(Contact, steps[0].contact_id)
    return None

def is_stale_wait(case: Case, stale_min: int | None = None) -> bool:
    if case.status != "waiting_other_team":
        return False
    stale_min = stale_min if stale_min is not None else settings.STALE_WAIT_MIN
    base = case.last_escalation_at or case.opened_at
    return age_minutes(base) > stale_min

def is_mttr_breach(case: Case) -> bool:
    if case.status == "resolved":
        return False
    return age_minutes(case.opened_at) > settings.MTTR_BREACH_MIN

def due_for_next_step(case: Case) -> bool:
    """True when current step's wait has elapsed and case unacknowledged."""
    if case.acknowledged_at or case.status == "resolved":
        return False
    if not case.last_escalation_at:
        return True
    return age_minutes(case.last_escalation_at) >= settings.ESC_STEP_WAIT_MIN

def make_ack_token() -> str:
    return secrets.token_urlsafe(24)

def acknowledge(db: Session, case: Case, by: str) -> None:
    case.acknowledged_by = by
    case.acknowledged_at = utcnow()
    if case.status == "open":
        case.status = "escalated"
    db.add(CaseEvent(case_id=case.id, at=utcnow(), engineer=by,
                     kind="escalation", text=f"Acknowledged by {by}. Escalation stopped."))
    # mark notifications acked
    for n in db.query(Notification).filter(Notification.case_id == case.id).all():
        if not n.ack_at:
            n.ack_at = utcnow()
    db.commit()

def recipients_for(db: Session, case: Case) -> list[Contact]:
    out: list[Contact] = []
    seen = set()
    prim = primary_contact(db, case)
    if prim:
        out.append(prim); seen.add(prim.id)
    for w in db.query(CaseWatcher).filter(CaseWatcher.case_id == case.id).all():
        c = db.get(Contact, w.contact_id)
        if c and c.id not in seen:
            out.append(c); seen.add(c.id)
    if case.link_id:
        link = db.get(Link, case.link_id)
        if link and link.standing_watcher_id:
            c = db.get(Contact, link.standing_watcher_id)
            if c and c.id not in seen:
                out.append(c); seen.add(c.id)
    return out
