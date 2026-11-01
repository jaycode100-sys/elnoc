"""MyShift — per-shift engineer notes + enforced shift close gate.

An engineer logs what happened on their shift (notes, extra info, power status).
The shift cannot be closed unless a power report exists for the date AND at
least one note exists (or an explicit "nothing to report" flag is set).

All dates are stored internally as ISO YYYY-MM-DD and formatted as DD/MM/YYYY
only at render time.
"""
from __future__ import annotations

import os
import re
import time
from datetime import datetime
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path

from ..database import get_db
from ..models import AppUser, PowerReport, ShiftNote, ShiftClose, Case
from ..security import get_current_user
from ..utils_time import utcnow, to_lagos
from ..schemas import (
    ShiftNoteCreate, ShiftNoteUpdate, ShiftNoteOut,
    ShiftCloseRequest, ShiftCloseOut,
    WhatsAppPasteRequest,
)

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

POWER_SOURCES = ("light", "big generator", "small generator", "inverter", "solar", "power tank")


def _lagos_date_iso() -> str:
    """Today's date in Lagos as ISO YYYY-MM-DD (canonical internal format)."""
    return to_lagos(utcnow()).strftime("%Y-%m-%d")


def _lagos_date_display(iso_date: str) -> str:
    """Format ISO YYYY-MM-DD as DD/MM/YYYY for display."""
    parts = iso_date.split("-")
    return f"{parts[2]}/{parts[1]}/{parts[0]}" if len(parts) == 3 else iso_date


def _shift_label() -> str:
    now_lagos = to_lagos(utcnow())
    return "day" if 7 <= now_lagos.hour < 19 else "night"


def _power_exists(db: Session, date_iso: str) -> bool:
    return db.query(PowerReport).filter(PowerReport.report_date == date_iso).first() is not None


def _shift_closed(db: Session, engineer: str, date_iso: str, shift: str) -> bool:
    return db.query(ShiftClose).filter(
        ShiftClose.engineer == engineer,
        ShiftClose.shift_date == date_iso,
        ShiftClose.shift == shift,
    ).first() is not None


# ---------------------------------------------------------------- page

@router.get("/myshift", response_class=HTMLResponse)
def myshift_page(request: Request, date: str = "",
                 user=Depends(get_current_user), db: Session = Depends(get_db)):
    # Accept either ISO (YYYY-MM-DD) or legacy DD/MM/YYYY; normalise to ISO
    d = date or _lagos_date_iso()
    if "/" in d:
        # Legacy DD/MM/YYYY -> ISO
        parts = d.split("/")
        if len(parts) == 3:
            d = f"{parts[2]}-{parts[1]}-{parts[0]}"
    shift = _shift_label()
    power_done = _power_exists(db, d)
    already_closed = _shift_closed(db, user.username, d, shift)
    from ..models import ShiftNote
    notes = db.query(ShiftNote).filter(
        ShiftNote.engineer == user.username,
        ShiftNote.shift_date == d,
        ShiftNote.shift == shift).order_by(
        ShiftNote.created_at.desc()).all()
    return templates.TemplateResponse(request, "myshift.html", {
        "user": user, "date": d, "date_display": _lagos_date_display(d),
        "shift": shift, "power_done": power_done, "already_closed": already_closed,
        "notes": notes, "power_sources": POWER_SOURCES})


# ---------------------------------------------------------------- API: save shift note

@router.post("/api/myshift/note")
def api_save_note(payload: ShiftNoteCreate, user=Depends(get_current_user),
                  db: Session = Depends(get_db)):
    d = payload.shift_date
    shift = payload.shift
    notes_text = (payload.notes or "").strip()
    extra_info = (payload.extra_info or "").strip()
    power_status = (payload.power_status or "").strip()
    if not notes_text and not extra_info and not power_status:
        return JSONResponse({"error": "nothing to save"}, status_code=400)
    # Reject if shift already closed (read-only after close)
    if _shift_closed(db, user.username, d, shift):
        return JSONResponse({"error": "shift already closed — notes are read-only"},
                            status_code=403)
    n = ShiftNote(engineer=user.username, shift_date=d, shift=shift,
                  notes=notes_text, extra_info=extra_info,
                  power_status=power_status, source=payload.source,
                  case_id=payload.case_id, created_at=utcnow())
    db.add(n); db.commit(); db.refresh(n)
    return JSONResponse({"id": n.id, "engineer": n.engineer, "shift_date": n.shift_date,
                         "shift": n.shift, "notes": n.notes, "extra_info": n.extra_info,
                         "power_status": n.power_status, "source": n.source,
                         "case_id": n.case_id,
                         "created_at": n.created_at.isoformat()})


# ---------------------------------------------------------------- API: edit note

@router.patch("/api/myshift/note/{note_id}")
def api_edit_note(note_id: int, payload: ShiftNoteUpdate, user=Depends(get_current_user),
                  db: Session = Depends(get_db)):
    from ..security import audit
    n = db.get(ShiftNote, note_id)
    if not n:
        return JSONResponse({"error": "note not found"}, status_code=404)
    if n.engineer != user.username:
        return JSONResponse({"error": "not your note"}, status_code=403)
    if _shift_closed(db, user.username, n.shift_date, n.shift):
        return JSONResponse({"error": "shift already closed — notes are read-only"},
                            status_code=403)
    if payload.notes is not None:
        n.notes = payload.notes
    if payload.extra_info is not None:
        n.extra_info = payload.extra_info
    if payload.power_status is not None:
        n.power_status = payload.power_status
    n.updated_at = utcnow()
    audit(db, "shift_note", str(n.id), user.username, "edited")
    db.commit()
    return JSONResponse({"id": n.id, "notes": n.notes, "extra_info": n.extra_info,
                         "power_status": n.power_status, "updated_at": n.updated_at.isoformat()})


# ---------------------------------------------------------------- API: delete note

@router.delete("/api/myshift/note/{note_id}")
def api_delete_note(note_id: int, user=Depends(get_current_user),
                    db: Session = Depends(get_db)):
    from ..security import audit
    n = db.get(ShiftNote, note_id)
    if not n:
        return JSONResponse({"error": "note not found"}, status_code=404)
    if n.engineer != user.username:
        return JSONResponse({"error": "not your note"}, status_code=403)
    if _shift_closed(db, user.username, n.shift_date, n.shift):
        return JSONResponse({"error": "shift already closed — notes are read-only"},
                            status_code=403)
    audit(db, "shift_note", str(n.id), user.username, "deleted")
    db.delete(n); db.commit()
    return JSONResponse({"deleted": note_id})


# ---------------------------------------------------------------- API: list notes

@router.get("/api/myshift/notes")
def api_list_notes(date: str = "", user=Depends(get_current_user),
                   db: Session = Depends(get_db)):
    d = date or _lagos_date_iso()
    if "/" in d:
        parts = d.split("/")
        if len(parts) == 3:
            d = f"{parts[2]}-{parts[1]}-{parts[0]}"
    shift = _shift_label()
    notes = db.query(ShiftNote).filter(
        ShiftNote.engineer == user.username,
        ShiftNote.shift_date == d,
        ShiftNote.shift == shift).order_by(
        ShiftNote.created_at.desc()).all()
    return JSONResponse([{"id": n.id, "notes": n.notes, "extra_info": n.extra_info,
                          "power_status": n.power_status, "source": n.source,
                          "case_id": n.case_id,
                          "created_at": n.created_at.isoformat(),
                          "updated_at": n.updated_at.isoformat() if n.updated_at else None}
                         for n in notes])


# ---------------------------------------------------------------- API: shift close gate (enforced)

@router.get("/api/myshift/can-close")
def api_can_close(date: str = "", user=Depends(get_current_user),
                  db: Session = Depends(get_db)):
    d = date or _lagos_date_iso()
    if "/" in d:
        parts = d.split("/")
        if len(parts) == 3:
            d = f"{parts[2]}-{parts[1]}-{parts[0]}"
    shift = _shift_label()
    power_done = _power_exists(db, d)
    already_closed = _shift_closed(db, user.username, d, shift)
    # Count notes for this engineer/date/shift
    from ..models import ShiftNote
    note_count = db.query(ShiftNote).filter(
        ShiftNote.engineer == user.username,
        ShiftNote.shift_date == d,
        ShiftNote.shift == shift).count()
    can_close = power_done and note_count > 0
    if already_closed:
        message = "Shift already closed."
    elif not power_done:
        message = "⚠ Power report required before shift close. Log power first."
    elif note_count == 0:
        message = "⚠ Log at least one shift note (or mark 'nothing to report') before closing."
    else:
        message = "Power report and notes logged — shift can close."
    return JSONResponse({"date": d, "date_display": _lagos_date_display(d),
                         "power_done": power_done, "note_count": note_count,
                         "already_closed": already_closed, "can_close": can_close,
                         "message": message})


# ---------------------------------------------------------------- API: enforce close

@router.post("/api/myshift/close")
def api_close_shift(payload: ShiftCloseRequest, user=Depends(get_current_user),
                    db: Session = Depends(get_db)):
    from ..security import audit
    d = _lagos_date_iso()
    shift = _shift_label()
    # Reject if already closed
    if _shift_closed(db, user.username, d, shift):
        return JSONResponse({"error": "shift already closed"}, status_code=409)
    # Gate: power report must exist
    power_report = db.query(PowerReport).filter(PowerReport.report_date == d).first()
    if not power_report:
        return JSONResponse({"error": "no power report for today — log power first"},
                            status_code=400)
    # Gate: at least one note OR explicit nothing_to_report
    from ..models import ShiftNote
    note_count = db.query(ShiftNote).filter(
        ShiftNote.engineer == user.username,
        ShiftNote.shift_date == d,
        ShiftNote.shift == shift).count()
    if note_count == 0 and not payload.nothing_to_report:
        return JSONResponse(
            {"error": "no shift notes logged — add a note or mark 'nothing to report'"},
            status_code=400)
    # Create close record
    sc = ShiftClose(engineer=user.username, shift_date=d, shift=shift,
                    power_report_id=power_report.id,
                    nothing_to_report=payload.nothing_to_report,
                    override_reason=payload.override_reason,
                    closed_at=utcnow())
    db.add(sc)
    audit(db, "shift_close", str(sc.id), user.username,
          f"date={d} shift={shift} power_report_id={power_report.id}")
    db.commit()
    # Append shift summary to handover (reuse existing handover service)
    try:
        from ..services.handover import append_shift_summary
        append_shift_summary(db, user.username, d, shift, notes=[],
                             power_report_id=power_report.id)
    except Exception:
        # Handover append is best-effort; close still succeeds
        pass
    db.commit()
    return JSONResponse({"id": sc.id, "engineer": sc.engineer, "shift_date": sc.shift_date,
                         "shift": sc.shift, "closed_at": sc.closed_at.isoformat(),
                         "power_report_id": sc.power_report_id,
                         "nothing_to_report": sc.nothing_to_report,
                         "message": "Shift closed."})


# ---------------------------------------------------------------- API: WhatsApp paste-in

@router.post("/api/myshift/whatsapp-paste")
def api_whatsapp_paste(payload: WhatsAppPasteRequest, user=Depends(get_current_user),
                       db: Session = Depends(get_db)):
    """Paste a WhatsApp conversation / escalation text; ELNOC parses and logs it."""
    raw = payload.raw_text.strip()
    d = payload.shift_date
    if not raw:
        return JSONResponse({"error": "nothing to paste"}, status_code=400)
    if _shift_closed(db, user.username, d, _shift_label()):
        return JSONResponse({"error": "shift already closed — notes are read-only"},
                            status_code=403)
    # Reuse power.py's parsers to avoid duplication
    from ..routers.power import _parse_battery_level, _parse_time, _infer_activity
    event_time = _parse_time(raw)
    battery = _parse_battery_level(raw)
    activity = _infer_activity(raw)
    notes_text = f"[WhatsApp paste] {raw}"
    extra_info = f"time={event_time} battery={battery} source=whatsapp"
    n = ShiftNote(engineer=user.username, shift_date=d, shift=_shift_label(),
                  notes=notes_text, extra_info=extra_info,
                  power_status=battery or "", source="whatsapp", created_at=utcnow())
    db.add(n); db.commit(); db.refresh(n)
    return JSONResponse({"id": n.id, "activity": activity, "event_time": event_time,
                         "battery_level": battery, "source": "whatsapp",
                         "notes": notes_text, "created_by": user.username,
                         "created_at": n.created_at.isoformat()})
