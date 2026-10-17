"""Pre-flight gate before a handover can be generated (both answers = YES).

  1. A DOWN case older than TICKET_WINDOW_MIN with no Phoenix ticket blocks.
  2. An unresolved case with nobody named to follow up with is auto-flagged.

Never a dead end: the engineer may override, but the override is recorded with
a reason and shows on the handover, so "we shipped it unticketed" is visible
rather than silent.
"""
from __future__ import annotations
from ..models import Case, AuditLog
from ..utils_time import utcnow, age_minutes
from .handover import _state, fmt_dur

TICKET_WINDOW_MIN = 30  # B5 item 25: ticket within 30 min of L1


def check(db, cases: list, now=None) -> dict:
    now = now or utcnow()
    blocks, flags = [], []
    for c in cases:
        name = (getattr(c, "_link_name", "") or f"CASE-{c.id}").upper()
        if c.status == "resolved":
            continue
        age = age_minutes(c.opened_at, now)
        if _state(c) == "down" and not (c.phoenix_ticket_no or "").strip() \
                and age >= TICKET_WINDOW_MIN:
            blocks.append({
                "case_id": c.id, "link": name, "reason": "no_phoenix_ticket",
                "detail": f"DOWN {fmt_dur(age)} with no Phoenix ticket "
                          f"(required within {TICKET_WINDOW_MIN} min of L1)",
            })
        if c.status != "resolved" and not (c.waiting_on or "").strip():
            flags.append({
                "case_id": c.id, "link": name, "reason": "no_waiting_party",
                "detail": "unresolved but nobody is named to follow up with",
            })
    return {"ok": not blocks, "blocks": blocks, "flags": flags,
            "ticket_window_min": TICKET_WINDOW_MIN}


def apply_override(db, cases: list, reason: str, user: str, now=None) -> dict:
    """Record an accepted override. Returns the check state."""
    now = now or utcnow()
    rep = check(db, cases, now)
    names = ", ".join(f"#{b['case_id']} {b['link']} ({b['reason']})"
                      for b in rep["blocks"]) or "none"
    db.add(AuditLog(entity="handover", entity_id="override", version=1,
                    changed_by=user, changed_at=now,
                    diff=f"Handover override accepted: {reason} | blocked: {names}"))
    db.commit()
    rep["overridden"] = True
    rep["override_reason"] = reason
    return rep