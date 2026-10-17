"""Which state is it really? DEGRADED vs UNSTABLE — decided from evidence,
then challenged to the duty officer (MCQ Q4=C, Q5=C).

  DEGRADED = link is UP but carrying errors/loss above threshold
  UNSTABLE  = link is flapping (cycles up/down, repeated state changes)

ELNOC computes the recommendation from monitoring history; it never silently
overrides the engineer. `challenge_text()` returns the two causes side by side
so the officer on duty must actively choose.
"""
from __future__ import annotations
from datetime import timedelta
from sqlalchemy.orm import Session
from ..models import Case, Event, OpticalReading
from ..utils_time import utcnow, ensure_utc

FLAP_WINDOW_MIN = 60
FLAP_MIN_CHANGES = 3
ERROR_THRESHOLD_PCT = 1.0   # error/loss ratio above which an UP link is degraded


def flapping(db: Session, link_id: int | None, device: str = "",
             now=None, window_min: int = FLAP_WINDOW_MIN) -> dict:
    """Count monitoring state transitions on this link in the window."""
    now = now or utcnow()
    since = ensure_utc(now) - timedelta(minutes=window_min)
    q = db.query(Event).filter(Event.occurred_at >= since)
    if link_id:
        q = q.filter(Event.link_id == link_id)
    elif device:
        q = q.filter(Event.device == device)
    evs = q.order_by(Event.occurred_at).all()
    changes, states = 0, []
    for e in evs:
        s = "down" if (e.type or "").lower() in ("down", "problem") else "up"
        if states and states[-1] != s:
            changes += 1
        states.append(s)
    return {"changes": changes, "samples": len(evs), "window_min": window_min,
            "flapping": changes >= FLAP_MIN_CHANGES,
            "last_state": states[-1] if states else ""}


def error_pressure(db: Session, link_id: int | None, device: str = "",
                   now=None, window_min: int = FLAP_WINDOW_MIN) -> dict:
    """Does an UP link look unhealthy? Uses RSL trend where we have readings."""
    now = now or utcnow()
    since = ensure_utc(now) - timedelta(minutes=window_min)
    q = db.query(OpticalReading).filter(OpticalReading.occurred_at >= since)
    if link_id:
        q = q.filter(OpticalReading.link_id == link_id)
    elif device:
        q = q.filter(OpticalReading.device == device)
    rows = [r.rsl_dbm for r in q.order_by(OpticalReading.occurred_at).all()
            if r.rsl_dbm is not None]
    if len(rows) < 2:
        return {"readings": len(rows), "degrading": False, "drop_db": 0.0,
                "avg_dbm": None}
    first, last = rows[0], rows[-1]
    drop = round(first - last, 2)  # dB of loss since the window started
    return {"readings": len(rows), "drop_db": drop,
            "avg_dbm": round(sum(rows) / len(rows), 2),
            # a material downward trend on a link that is nominally up
            "degrading": drop >= 3.0}


def recommend(db: Session, case: Case, now=None) -> dict:
    """Recommendation with the evidence behind it — never applied silently."""
    f = flapping(db, case.link_id, case.device or "", now)
    e = error_pressure(db, case.link_id, case.device or "", now)
    if f["flapping"]:
        state, why = "unstable", (
            f"{f['changes']} state changes in {f['window_min']} min (threshold "
            f"{FLAP_MIN_CHANGES}) — flapping")
    elif e["degrading"]:
        state, why = "degraded", (
            f"link reads UP but RSL fell {e['drop_db']} dB across "
            f"{e['readings']} readings — errors/loss above threshold")
    else:
        state, why = "degraded", "no flapping and no clear degradation signal — engineer decides"
    return {"recommended": state, "why": why, "flapping": f, "errors": e}


def challenge_text(rec: dict) -> str:
    """The two causes, side by side, so the officer must choose."""
    return (
        "CHOOSE THE STATE — ELNOC cannot decide this for you:\n"
        f"  DEGRADED = link is UP but carrying errors/loss above threshold\n"
        f"  UNSTABLE  = link is flapping (cycles up/down, repeated state changes)\n"
        f"ELNOC's read: {rec['recommended'].upper()} — {rec['why']}\n"
        "If you disagree, set the state yourself and say why in a note."
    )


def challenge_card(rec: dict) -> dict:
    """Compact version for the UI banner."""
    if rec["flapping"]["flapping"]:
        detail = (f"{rec['flapping']['changes']} state changes in "
                  f"{rec['flapping']['window_min']} min")
    elif rec["errors"]["readings"] >= 2:
        detail = (f"RSL moved {rec['errors']['drop_db']} dB over "
                  f"{rec['errors']['readings']} readings")
    else:
        detail = "insufficient monitoring signal — human call"
    return {"recommended": rec["recommended"], "detail": detail,
            "flapping": rec["flapping"]["flapping"],
            "degrading": rec["errors"]["degrading"]}