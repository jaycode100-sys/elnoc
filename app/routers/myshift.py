"""MyShift — per-shift engineer notes + shift close gate.

An engineer logs what happened on their shift (notes, extra info, power status),
and the shift cannot be closed unless a power report exists for the date.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path

from ..database import get_db
from ..models import AppUser, PowerReport
from ..security import get_current_user
from ..utils_time import utcnow, to_lagos, fmt_date

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

POWER_SOURCES = ("light", "big generator", "small generator", "inverter", "solar", "power tank")


def _lagos_date() -> str:
    return to_lagos(utcnow()).strftime("%d/%m/%Y")


def _shift_label() -> str:
    now_lagos = to_lagos(utcnow())
    return "day" if 7 <= now_lagos.hour < 19 else "night"


def _power_exists(db: Session, date_str: str) -> bool:
    return db.query(PowerReport).filter(PowerReport.report_date == date_str).first() is not None


# ---------------------------------------------------------------- page

@router.get("/myshift", response_class=HTMLResponse)
def myshift_page(request: Request, date: str = "",
                 user=Depends(get_current_user), db: Session = Depends(get_db)):
    d = date or _lagos_date()
    shift = _shift_label()
    power_done = _power_exists(db, d)
    # existing notes for this engineer / date / shift
    from ..models import ShiftNote
    notes = db.query(ShiftNote).filter(
        ShiftNote.engineer == user.username,
        ShiftNote.shift_date == d,
        ShiftNote.shift == shift).order_by(ShiftNote.created_at.desc()).all()
    return templates.TemplateResponse(request, "myshift.html", {
        "user": user, "date": d, "shift": shift, "power_done": power_done,
        "notes": notes, "power_sources": POWER_SOURCES})


# ---------------------------------------------------------------- API: save shift note

@router.post("/api/myshift/note")
def api_save_note(payload: dict, user=Depends(get_current_user),
                  db: Session = Depends(get_db)):
    from ..models import ShiftNote
    shift_date = (payload.get("shift_date") or _lagos_date()).strip()
    shift = (payload.get("shift") or _shift_label()).strip()
    notes_text = (payload.get("notes") or "").strip()
    extra_info = (payload.get("extra_info") or "").strip()
    power_status = (payload.get("power_status") or "").strip()
    if not notes_text and not extra_info and not power_status:
        return JSONResponse({"error": "nothing to save"}, status_code=400)
    n = ShiftNote(engineer=user.username, shift_date=shift_date, shift=shift,
                  notes=notes_text, extra_info=extra_info,
                  power_status=power_status, created_at=utcnow())
    db.add(n); db.commit(); db.refresh(n)
    return JSONResponse({"id": n.id, "engineer": n.engineer, "shift_date": n.shift_date,
                         "shift": n.shift, "notes": n.notes, "extra_info": n.extra_info,
                         "power_status": n.power_status,
                         "created_at": n.created_at.isoformat()})


# ---------------------------------------------------------------- API: shift close gate

@router.get("/api/myshift/can-close")
def api_can_close(date: str = "", user=Depends(get_current_user),
                  db: Session = Depends(get_db)):
    d = date or _lagos_date()
    power_done = _power_exists(db, d)
    return JSONResponse({"date": d, "power_done": power_done,
                         "can_close": power_done,
                         "message": "Power report logged — shift can close." if power_done
                         else "⚠ Power report required before shift close. Log power first."})


# ---------------------------------------------------------------- API: list notes

@router.get("/api/myshift/notes")
def api_list_notes(date: str = "", user=Depends(get_current_user),
                   db: Session = Depends(get_db)):
    from ..models import ShiftNote
    d = date or _lagos_date()
    shift = _shift_label()
    notes = db.query(ShiftNote).filter(
        ShiftNote.engineer == user.username,
        ShiftNote.shift_date == d,
        ShiftNote.shift == shift).order_by(ShiftNote.created_at.desc()).all()
    return JSONResponse([{"id": n.id, "notes": n.notes, "extra_info": n.extra_info,
                          "power_status": n.power_status,
                          "created_at": n.created_at.isoformat()} for n in notes])


# ---------------------------------------------------------------- Webhook: WhatsApp paste-in

@router.post("/api/myshift/whatsapp-paste")
def api_whatsapp_paste(payload: dict, user=Depends(get_current_user),
                       db: Session = Depends(get_db)):
    """Paste a WhatsApp conversation / escalation text; ELNOC parses and logs it."""
    raw = (payload.get("raw_text") or "").strip()
    shift_date = (payload.get("shift_date") or _lagos_date()).strip()
    if not raw:
        return JSONResponse({"error": "nothing to paste"}, status_code=400)
    from ..models import ShiftNote
    # Heuristic parse: look for source lines
    text_lower = raw.lower()
    source = "whatsapp"
    # Try to extract a time
    import re
    time_m = re.search(r"(\d{1,2}:\d{2}\s*(?:AM|PM))", raw, re.I)
    event_time = time_m.group(1).upper() if time_m else ""
    # Try to extract battery level
    batt_m = re.search(r"([0-9]{1,3}%)", raw)
    battery = batt_m.group(1) if batt_m else ""
    activity = "WhatsApp paste: " + (raw[:80] + "..." if len(raw) > 80 else raw)
    notes_text = f"[WhatsApp paste] {raw}"
    extra_info = f"time={event_time} battery={battery} source=whatsapp"
    n = ShiftNote(engineer=user.username, shift_date=shift_date, shift=_shift_label(),
                  notes=notes_text, extra_info=extra_info,
                  power_status=battery or "", created_at=utcnow())
    db.add(n); db.commit(); db.refresh(n)
    return JSONResponse({"id": n.id, "activity": activity, "event_time": event_time,
                         "battery_level": battery, "source": source,
                         "notes": notes_text, "created_by": user.username,
                         "created_at": n.created_at.isoformat()})
