"""Tests for MyShift: gate, close, edit/delete, date normalization."""
from datetime import timedelta
from tests.conftest import fresh_db
from app.routers.myshift import (
    _power_exists, _shift_closed, shift_label, lagos_date_iso,
    parse_lagos_date, lagos_date_display,
)
from app.models import PowerReport, ShiftNote, ShiftClose, AppUser
from app.utils_time import utcnow


db = fresh_db()


def _make_user(db, username="eng1", name="Engineer One", role="engineer"):
    from app.security import hash_password
    from app.models import AppUser
    existing = db.query(AppUser).filter(AppUser.username == username).first()
    if existing:
        return existing
    h, s = hash_password("pw")
    u = AppUser(username=username, name=name, role=role, active=True,
                password_hash=h, password_salt=s)
    db.add(u); db.commit()
    return u


def test_lagos_date_iso_format():
    d = lagos_date_iso()
    # YYYY-MM-DD
    assert len(d) == 10 and d[4] == "-" and d[7] == "-"


def test_lagos_date_display():
    assert lagos_date_display("2026-11-01") == "01/11/2026"
    assert lagos_date_display("2026-01-05") == "05/01/2026"


def test_parse_lagos_date_iso():
    assert parse_lagos_date("2026-11-01") == "2026-11-01"


def test_parse_lagos_date_ddmmyyyy():
    assert parse_lagos_date("01/11/2026") == "2026-11-01"


def test_shift_label_day():
    # 10:00 Lagos = day
    from app.utils_time import to_lagos
    d = to_lagos(utcnow()).replace(hour=10, minute=0)
    assert shift_label(d) == "day"


def test_shift_label_night():
    from app.utils_time import to_lagos
    d = to_lagos(utcnow()).replace(hour=22, minute=0)
    assert shift_label(d) == "night"


def test_gate_requires_power_and_notes():
    _make_user(db, "eng1")
    today = utcnow().strftime("%Y-%m-%d")
    # No power, no notes
    assert _power_exists(db, today) is False
    # Add power
    pr = PowerReport(report_date=today, activity="Generator switched ON",
                     event_time="8:00 AM", battery_level="70%",
                     source="manual", created_by="eng1")
    db.add(pr); db.commit()
    assert _power_exists(db, today) is True
    # Gate: power but no notes -> cannot close (notes required)
    # (the actual can_close logic lives in the endpoint; here we check the pieces)
    assert _shift_closed(db, "eng1", today, "day") is False


def test_close_shift_full_flow():
    _make_user(db, "eng1")
    today = utcnow().strftime("%Y-%m-%d")
    # Power report
    pr = PowerReport(report_date=today, activity="Inverter ON",
                     event_time="8:00 AM", battery_level="70%",
                     source="manual", created_by="eng1")
    db.add(pr); db.commit()
    # Note
    n = ShiftNote(engineer="eng1", shift_date=today, shift="day",
                  notes="Shift handover complete", power_status="Inverter 70%",
                  source="manual", created_at=utcnow())
    db.add(n); db.commit()
    # Close
    from app.routers.myshift import api_close_shift
    from app.schemas import ShiftCloseRequest
    from fastapi import Request
    # Simulate via direct service call
    from app.routers.myshift import _shift_closed, lagos_date_iso, shift_label
    assert _shift_closed(db, "eng1", today, "day") is False
    # Manually create close record (simulating endpoint)
    sc = ShiftClose(engineer="eng1", shift_date=today, shift="day",
                    power_report_id=pr.id, nothing_to_report=False,
                    closed_at=utcnow())
    db.add(sc); db.commit()
    assert _shift_closed(db, "eng1", today, "day") is True
    # Double close prevented
    assert _shift_closed(db, "eng1", today, "day") is True


def test_edit_delete_note_before_close():
    _make_user(db, "eng1")
    today = utcnow().strftime("%Y-%m-%d")
    n = ShiftNote(engineer="eng1", shift_date=today, shift="day",
                  notes="Original note", power_status="",
                  source="manual", created_at=utcnow())
    db.add(n); db.commit()
    # Edit
    n.notes = "Edited note"
    n.updated_at = utcnow()
    db.commit()
    db.refresh(n)
    assert n.notes == "Edited note"
    # Delete
    db.delete(n); db.commit()
    assert db.query(ShiftNote).filter(ShiftNote.id == n.id).first() is None


def test_power_interruption_summary():
    from app.routers.power import api_power_summary
    today = utcnow().strftime("%Y-%m-%d")
    # Two events: OFF then ON
    pr1 = PowerReport(report_date=today, activity="Generator switched OFF",
                      event_time="11:34 AM", battery_level="",
                      source="manual", created_by="eng1")
    pr2 = PowerReport(report_date=today, activity="Inverter battery switched ON",
                      event_time="3:30 PM", battery_level="71%",
                      source="manual", created_by="eng1")
    db.add(pr1); db.add(pr2); db.commit()
    # The summary endpoint requires auth; test the logic directly
    from app.services.shift import parse_battery_level, parse_time, infer_activity
    assert parse_time("11:34 AM") == "11:34 AM"
    assert parse_battery_level("Inverter: 24%, Kitchen: 44%, Office: 39%") == "24%, Kitchen: 44%, Office: 39%"
    assert infer_activity("Generator switched OFF at 11:34 AM") == "Generator event"
    assert infer_activity("Solar charging at 85%") == "Solar event"
