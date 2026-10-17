"""Handover detail rules: UNSTABLE state, SHIFT SUMMARY block, Phoenix ticket
numbers are APP-ONLY (never in the handover text)."""
from datetime import timedelta

from tests.conftest import fresh_db
from app.database import SessionLocal
from app.models import Case, Link
from app.services.handover import (
    build_handover_text, build_summary, assert_no_ticket_leak, _state)
from app.services.escalation import is_stale_wait
from app.utils_time import utcnow

db = fresh_db()


def _mk(link, state, waiting="", symptom="x", phoenix="", restored_hours_ago=None,
        fix="", level=""):
    c = Case(engineer="t", customer_id=link.customer_id, link_id=link.id,
             symptom=symptom, status="open", severity="critical",
             link_state=state, waiting_on=waiting, opened_at=utcnow() - timedelta(hours=6),
             phoenix_ticket_no=phoenix, fix=fix, escalation_level=level)
    if restored_hours_ago is not None:
        c.restored_at = utcnow() - timedelta(hours=restored_hours_ago)
    db.add(c); db.flush()
    c._link_name = link.name
    c._latest_note = symptom
    c._affected = []
    return c


def test_unstable_is_its_own_state_not_down():
    link = db.query(Link).first()
    u = _mk(link, "unstable", symptom="flapping")
    assert _state(u) == "unstable"
    text = build_handover_text([u], "16/10/2026", summary=False)
    assert "STATUS: UNSTABLE" in text
    assert "UNRESOLVED LINKS" in text  # unstable is NOT resolved


def test_unknown_state_falls_back_to_down():
    link = db.query(Link).first()
    c = _mk(link, "weird-state")
    assert _state(c) == "down"


def test_summary_tallies_states_and_names_duty():
    link = db.query(Link).first()
    d = _mk(link, "down", waiting="OREGUN TEAM", symptom="dark")
    g = _mk(link, "degraded", symptom="lossy")
    u = _mk(link, "unstable", symptom="flap")
    up = _mk(link, "up", symptom="restored", restored_hours_ago=1, fix="SFP replaced")
    text = build_summary([d, g, u, up], "16/10/2026",
                         from_engineer="Day Engineer", to_engineer="Night Engineer")
    assert "ON SHIFT DUTY: DAY ENGINEER" in text
    assert "INCOMING: NIGHT ENGINEER" in text
    assert "TICKETS THIS HANDOVER: 4" in text
    assert "DOWN 1" in text and "DEGRADED 1" in text and "UNSTABLE 1" in text and "UP 1" in text
    assert "LINK RESTORATION UPDATE (LAST 12H)" in text
    assert "WAT" in text and "SFP replaced" in text
    assert "STILL UNRESOLVED AT HANDOVER: 3" in text
    assert "WITH OREGUN TEAM" in text
    db.rollback()


def test_summary_reports_none_restored():
    link = db.query(Link).first()
    c = _mk(link, "down")
    text = build_summary([c], "16/10/2026")
    assert "NONE RESTORED IN THIS WINDOW" in text
    db.rollback()


def test_restored_window_excludes_older_than_window():
    link = db.query(Link).first()
    old = _mk(link, "up", restored_hours_ago=40, fix="old")
    text = build_summary([old], "16/10/2026", restored_hours=12)
    assert "NONE RESTORED" in text
    db.rollback()


def test_ticket_numbers_never_leak_into_handover():
    link = db.query(Link).first()
    c = _mk(link, "down", symptom="far end dark", phoenix="PHX-4821")
    text = build_handover_text([c], "16/10/2026", summary=True)
    assert "PHX-4821" not in text, text
    assert "phoenix" not in text.lower()
    db.rollback()


def test_ticket_guard_raises_on_leak():
    try:
        assert_no_ticket_leak("STATUS: DOWN\nUPDATE: see Phoenix PHX-1")
    except ValueError:
        return
    raise AssertionError("guard should have raised")


def test_summary_appended_by_default_and_can_be_off():
    link = db.query(Link).first()
    c = _mk(link, "down")
    assert "SHIFT SUMMARY" in build_handover_text([c], "16/10/2026")
    assert "SHIFT SUMMARY" not in build_handover_text([c], "16/10/2026", summary=False)
    db.rollback()


def test_status_route_stamps_ticket_and_restored():
    from app.routers.cases import change_status
    from types import SimpleNamespace
    sdb = SessionLocal()
    try:
        link = sdb.query(Link).first()
        c = Case(engineer="t", customer_id=link.customer_id, link_id=link.id,
                 symptom="x", status="open", opened_at=utcnow())
        sdb.add(c); sdb.commit()
        u = SimpleNamespace(username="t", role="engineer")
        change_status(c.id, status="open", link_state="up", waiting_on="",
                      escalation_level="", phoenix_ticket_no="PHX-77", user=u, db=sdb)
        got = sdb.get(Case, c.id)
        assert got.phoenix_ticket_no == "PHX-77"
        assert got.phoenix_ticket_opened_at is not None
        assert got.restored_at is not None  # stamped when declared up
    finally:
        sdb.close()