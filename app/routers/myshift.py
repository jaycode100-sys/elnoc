"""MyShift — per-shift engineer notes + enforced shift close gate.

An engineer logs what happened on their shift (notes, extra info, power status).
The shift cannot be closed unless a power report exists for the date AND at
least one note exists (or an explicit "nothing to report" flag is set).

All dates are stored internally as ISO YYYY-MM-DD and formatted as DD/MM/YYYY
only at render time.
"""
from __future__ import annotations

from datetime import datetime
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path

from ..database import get_db
from ..models import AppUser, PowerReport, ShiftNote, ShiftClose, Case
from ..security import get_current_user
from ..services.shift import (
    lagos_date_iso, lagos_date_display, parse_lagos_date, shift_label,
    shift_label_from_roster,
    parse_battery_level, parse_time, infer_activity,
    POWER_SOURCES,
)
from ..schemas import (
    ShiftNoteCreate, ShiftNoteUpdate, ShiftNoteOut,
    ShiftCloseRequest, ShiftCloseOut,
    WhatsAppPasteRequest,
)

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


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
    d = parse_lagos_date(date or lagos_date_iso())
    shift = shift_label_from_roster(db, user.username, d)
    power_exists = _power_exists(db, d)
    already_closed = _shift_closed(db, user.username, d, shift)
    notes = db.query(ShiftNote).filter(
        ShiftNote.engineer == user.username,
        ShiftNote.shift_date == d,
        ShiftNote.shift == shift).order_by(
        ShiftNote.created_at.desc()).all()
    return templates.TemplateResponse(request, "myshift.html", {
        "user": user, "date": d, "date_display": lagos_date_display(d),
        "shift": shift, "power_done": power_exists, "already_closed": already_closed,
        "notes": notes, "power_sources": POWER_SOURCES})


# ---------------------------------------------------------------- API: save shift note

@router.post("/api/myshift/note")
def api_save_note(payload: ShiftNoteCreate, user=Depends(get_current_user),
                  db: Session = Depends(get_db)):
    d = payload.shift_date
    shift = shift_label_from_roster(db, user.username, d)
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
    d = parse_lagos_date(date or lagos_date_iso())
    shift = shift_label()
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


# ---------------------------------------------------------------- API: notes linked to a case

@router.get("/api/myshift/notes/case/{case_id}")
def api_notes_for_case(case_id: int, user=Depends(get_current_user),
                       db: Session = Depends(get_db)):
    """Get shift notes linked to a case (for the case page sidebar)."""
    notes = db.query(ShiftNote).filter(
        ShiftNote.case_id == case_id,
        ShiftNote.engineer == user.username).order_by(
        ShiftNote.created_at.desc()).all()
    return JSONResponse([{"id": n.id, "notes": n.notes, "extra_info": n.extra_info,
                          "power_status": n.power_status, "source": n.source,
                          "shift_date": n.shift_date, "shift": n.shift,
                          "created_at": n.created_at.isoformat()}
                         for n in notes])


# ---------------------------------------------------------------- API: shift close gate (enforced)

@router.get("/api/myshift/can-close")
def api_can_close(date: str = "", user=Depends(get_current_user),
                  db: Session = Depends(get_db)):
    d = parse_lagos_date(date or lagos_date_iso())
    shift = shift_label_from_roster(db, user.username, d)
    power_done = _power_exists(db, d)
    already_closed = _shift_closed(db, user.username, d, shift)
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
    return JSONResponse({"date": d, "date_display": lagos_date_display(d),
                         "power_done": power_done, "note_count": note_count,
                         "already_closed": already_closed, "can_close": can_close,
                         "message": message})


# ---------------------------------------------------------------- API: enforce close

@router.post("/api/myshift/close")
def api_close_shift(payload: ShiftCloseRequest, user=Depends(get_current_user),
                    db: Session = Depends(get_db)):
    from ..security import audit
    d = lagos_date_iso()
    shift = shift_label_from_roster(db, user.username, d)
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


# ---------------------------------------------------------------- API: lead view

@router.get("/api/myshift/summary")
def api_myshift_summary(date: str = "", user=Depends(get_current_user),
                        db: Session = Depends(get_db)):
    """Lead view: all engineers' notes, power status, and close state for a date."""
    d = parse_lagos_date(date or lagos_date_iso())
    shifts = ("day", "night")
    engineers = db.query(AppUser).filter(AppUser.active == True).all()  # noqa: E712
    result = []
    for eng in engineers:
        for shift in shifts:
            notes = db.query(ShiftNote).filter(
                ShiftNote.engineer == eng.username,
                ShiftNote.shift_date == d,
                ShiftNote.shift == shift).order_by(
                ShiftNote.created_at.desc()).all()
            closed = _shift_closed(db, eng.username, d, shift)
            power_done = _power_exists(db, d)
            note_texts = [n.notes for n in notes if n.notes.strip()]
            result.append({
                "engineer": eng.username,
                "engineer_name": eng.name or eng.username,
                "role": eng.role,
                "shift_date": d,
                "shift": shift,
                "note_count": len(notes),
                "notes": note_texts,
                "power_done": power_done,
                "closed": closed,
                "can_close": power_done and (len(note_texts) > 0),
            })
    return JSONResponse({"date": d, "date_display": lagos_date_display(d),
                         "engineers": result})

@router.post("/api/myshift/whatsapp-paste")
def api_whatsapp_paste(payload: WhatsAppPasteRequest, user=Depends(get_current_user),
                       db: Session = Depends(get_db)):
    """Paste a WhatsApp conversation / escalation text; ELNOC parses and logs it.
    
    If the paste contains power-related content (generator, inverter, solar,
    power tank, light, mains), a PowerReport row is also created so it
    satisfies the shift-close gate.
    """
    raw = payload.raw_text.strip()
    d = payload.shift_date
    if not raw:
        return JSONResponse({"error": "nothing to paste"}, status_code=400)
    if _shift_closed(db, user.username, d, shift_label_from_roster(db, user.username, d)):
        return JSONResponse({"error": "shift already closed — notes are read-only"},
                            status_code=403)
    # Use shared helpers from app/services/shift.py
    event_time = parse_time(raw)
    battery = parse_battery_level(raw)
    activity = infer_activity(raw)
    notes_text = f"[WhatsApp paste] {raw}"
    extra_info = f"time={event_time} battery={battery} source=whatsapp"
    n = ShiftNote(engineer=user.username, shift_date=d, shift=shift_label_from_roster(db, user.username, d),
                  notes=notes_text, extra_info=extra_info,
                  power_status=battery or "", source="whatsapp", created_at=utcnow())
    db.add(n); db.flush(); db.refresh(n)

    # If the paste mentions a power source, also create a PowerReport row
    # so it satisfies the shift-close gate.
    power_report_id = None
    lower = raw.lower()
    if any(src in lower for src in POWER_SOURCES):
        pr = PowerReport(report_date=d, activity=activity or "Power event",
                         event_time=event_time, battery_level=battery or "",
                         source="whatsapp", raw_text=raw,
                         summary=f"{activity} at {event_time or 'time not stated'} — {battery or 'level not stated'}",
                         created_by=user.username)
        db.add(pr); db.flush(); db.refresh(pr)
        power_report_id = pr.id

    db.commit()
    return JSONResponse({"id": n.id, "activity": activity, "event_time": event_time,
                         "battery_level": battery, "source": "whatsapp",
                         "power_report_id": power_report_id,
                         "notes": notes_text, "created_by": user.username,
                         "created_at": n.created_at.isoformat()})


# ---------------------------------------------------------------- API: search shift notes

@router.get("/api/myshift/search")
def api_search_notes(q: str = "", user=Depends(get_current_user),
                     db: Session = Depends(get_db)):
    """Search shift notes by keyword (full-text, ILIKE)."""
    q = (q or "").strip()
    if not q:
        return JSONResponse({"results": []})
    q_lower = q.lower()
    notes = db.query(ShiftNote).filter(
        ShiftNote.engineer == user.username,
        ShiftNote.notes.ilike(f"%{q}%")
    ).order_by(ShiftNote.created_at.desc()).limit(50).all()
    return JSONResponse({"results": [{"id": n.id, "notes": n.notes, "extra_info": n.extra_info,
                                      "power_status": n.power_status, "shift_date": n.shift_date,
                                      "shift": n.shift, "created_at": n.created_at.isoformat(),
                                      "case_id": n.case_id} for n in notes]})
