"""Dispatcher: per-channel delivery log (FR-34, gap #5), retries (NFR-06)."""
from __future__ import annotations
from sqlalchemy.orm import Session
from ..models import Case, Contact, Notification, CaseEvent
from ..utils_time import utcnow
from ..services.escalation import make_ack_token, recipients_for
from .templates import render_notification
from . import channels

def notify_case(db: Session, case: Case, event_summary: str = "",
                affected: str = "", dry_run: bool = True,
                force_channels: list[str] | None = None) -> list[Notification]:
    recips = recipients_for(db, case)
    rows: list[Notification] = []
    for contact in recips:
        wanted = [c.strip().lower() for c in (contact.preferred_channels or "email,whatsapp").split(",")]
        if force_channels:
            wanted = force_channels
        for ch in wanted:
            token = make_ack_token()
            body = render_notification(case, event_summary, affected or contact.team).replace("{token}", token)
            if ch == "email" and contact.email:
                res = channels.send_email(contact.email, f"NOC case {case.id} | {case.severity}", body, dry_run=dry_run)
                dest = contact.email
            elif ch == "whatsapp" and contact.whatsapp_number:
                # template for critical new/escalated so night alerts deliver (sec 10.4)
                tmpl = None
                if (case.severity or "").lower() == "critical":
                    tmpl = None  # free-form inside window; admin sets template name in .env when approved
                res = channels.send_whatsapp(contact.whatsapp_number, body, template=tmpl, dry_run=dry_run)
                dest = contact.whatsapp_number
            elif ch == "sms" and contact.phone:
                res = channels.send_sms(contact.phone, body, dry_run=dry_run)
                dest = contact.phone
            else:
                continue
            n = Notification(case_id=case.id, event_key="", contact_id=contact.id,
                             channel=ch, status="sent" if res.ok else "failed",
                             sent_at=utcnow() if res.ok else None,
                             error="" if res.ok else f"{dest}: {res.error}",
                             ack_token=token)
            db.add(n)
            rows.append(n)
    db.add(CaseEvent(case_id=case.id, at=utcnow(), engineer="system", kind="notification",
                     text=f"Notified {len(recips)} recipient(s) on {[r.channel for r in rows]}."))
    case.last_escalation_at = utcnow()
    db.commit()
    return rows

def retry_failed(db: Session, dry_run: bool = True) -> int:
    """NFR-06: failed stays unsent until at least one channel delivers."""
    failed = db.query(Notification).filter(Notification.status == "failed").all()
    n = 0
    for row in failed:
        contact = db.get(Contact, row.contact_id) if row.contact_id else None
        if not contact:
            continue
        case = db.get(Case, row.case_id)
        body = f"Retry NOC case {row.case_id} via {row.channel}"
        if row.channel == "email":
            res = channels.send_email(contact.email, body, body, dry_run=dry_run)
        elif row.channel == "whatsapp":
            res = channels.send_whatsapp(contact.whatsapp_number, body, dry_run=dry_run)
        else:
            res = channels.send_sms(contact.phone, body, dry_run=dry_run)
        if res.ok:
            row.status = "sent"
            row.sent_at = utcnow()
            row.error = ""
            n += 1
        else:
            row.error = res.error
    db.commit()
    return n
