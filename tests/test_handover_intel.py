"""Handover intel: tolerant WhatsApp parsing, 12h/48h update watch, import
apply, escalation levels. Synthetic names in the team's real shapes."""
from datetime import timedelta
from types import SimpleNamespace

from tests.conftest import fresh_db
from app.database import SessionLocal
from app.models import Case, CaseEvent, Link, ESCALATION_LEVELS
from app.services.handover_parse import (
    parse_handover, normalize_status, extract_party)
from app.services.update_watch import watch_updates, flag_text, normalize_update
from app.utils_time import utcnow

db = fresh_db()

SAMPLE = """TICKET UPDATES – 16/10/2026
UNRESOLVED LINKS

LTV8 Ikeja-RC
STATUS: DOWN
UPDATE: FOLLOWING UP WITH OREGUN TEAM | far end still dark

Demo Bank HQ
STATUS : DEGRADED
FOLLOWING UP WITH PREC PEARL TEAM

Mystery Fibre Link
STATUS:DOWN
UPDATE: FOLLOWING UIP WITH ISLAND TEAM
AFFECTED LINKS: Alpha, Beta Backup
-------------------------------------------------
-------------------------------------------------
Oddball Entry
STATUS: AWAITING CONFIRMATION FROM CUSTOMER

RESOLVED LINKS

Prec Pearl Main
STATUS: UP | power restored at site
"""

def test_parser_reads_real_world_variants():
    p = parse_handover(SAMPLE)
    assert p["date"] == "16/10/2026"
    assert p["warnings"] == [], p["warnings"]
    assert [e["link"] for e in p["unresolved"]] == [
        "LTV8 Ikeja-RC", "Demo Bank HQ", "Mystery Fibre Link", "Oddball Entry"]
    ltv, demo, mystery, odd = p["unresolved"]
    assert (ltv["link_state"], ltv["status_raw"]) == ("down", "DOWN")
    assert ltv["update"] == "FOLLOWING UP WITH OREGUN TEAM | far end still dark"
    assert demo["link_state"] == "degraded"  # 'STATUS : DEGRADED' spacing
    assert demo["update"] == "FOLLOWING UP WITH PREC PEARL TEAM"  # bare line, no UPDATE:
    assert mystery["link_state"] == "down"  # 'STATUS:DOWN' no space
    assert mystery["affected"] == ["Alpha", "Beta Backup"]  # inline style
    assert odd["link_state"] is None and odd["status_raw"] == "AWAITING CONFIRMATION FROM CUSTOMER"
    res = p["resolved"][0]
    assert res["link"] == "Prec Pearl Main" and res["link_state"] == "up"
    assert res["update"] == "power restored at site"  # resolved bar-note kept

def test_parser_head_style_affected_and_bare_follow_typo():
    p = parse_handover("TICKET UPDATES – 17/10/2026\nUNRESOLVED LINKS\n\n"
                       "Some Link\nSTATUS: DOWN\nUPDATE: x\nLINKS AFFECTED\n"
                       "Goodluck, Zetaweb Backup\n")
    assert p["unresolved"][0]["affected"] == ["Goodluck", "Zetaweb Backup"]
    assert extract_party("FOLLOWING UIP WITH ISLAND TEAM") == "ISLAND TEAM"
    assert extract_party("FOLLOWING UP WITH OREGUN TEAM | far end dark") == "OREGUN TEAM"
    assert extract_party("TEAM TO REPLACE SFP, FOLLOWING UP WITH NETWORKING TEAM") == "NETWORKING TEAM"
    assert extract_party("no party here") == ""

def test_normalize_status_variants():
    assert normalize_status("DOWN")[0] == "down"
    assert normalize_status("up | issue is from angola cables") == ("up", "UP", "issue is from angola cables")  # note keeps its case
    assert normalize_status("Awaiting confirmation")[0] is None

def _ev(hours_ago, kind, text):
    return SimpleNamespace(at=utcnow() - timedelta(hours=hours_ago),
                           kind=kind, text=text)

def test_watch_thresholds():
    fresh = watch_updates("link down", utcnow() - timedelta(hours=2),
                          [_ev(1, "note", "chased oregun, new ticket")])
    assert fresh["state"] == "fresh" and not flag_text(fresh)
    q = watch_updates("FOLLOWING UP WITH OREGUN TEAM",
                      utcnow() - timedelta(hours=30),
                      [_ev(20, "note", "following up with Oregun team")])
    assert q["state"] == "question" and "QUESTION IT" in flag_text(q)
    r = watch_updates("FOLLOWING UP WITH OREGUN TEAM",
                      utcnow() - timedelta(hours=60),
                      [_ev(50, "note", "Following   up with  OREGUN team.")])
    assert r["state"] == "repeat" and "REPEAT" in flag_text(r)
    assert r["runs"] == 2  # symptom + one identical note

def test_watch_change_resets_clock():
    w = watch_updates("down", utcnow() - timedelta(hours=60),
                      [_ev(50, "note", "waiting oregun"),
                       _ev(2, "note", "RSL checked, far end dark confirmed")])
    assert w["state"] == "fresh" and w["runs"] == 1

def test_watch_ignores_non_notes():
    w = watch_updates("down", utcnow() - timedelta(hours=60),
                      [_ev(50, "system", "down"),
                       _ev(50, "escalation", "down"),
                       _ev(50, "notification", "down")])
    assert w["state"] == "repeat"  # nothing new said for 60h

def test_levels_known():
    assert set(ESCALATION_LEVELS) == {"L1", "L2", "L3", "Vendor"}
    assert "first-line" in ESCALATION_LEVELS["L1"]
    assert "separate path" in ESCALATION_LEVELS["Vendor"]

def test_status_route_sets_level_and_rejects_junk():
    from app.routers.cases import change_status
    sdb = SessionLocal()
    try:
        link = sdb.query(Link).first()
        c = Case(engineer="t", customer_id=link.customer_id, link_id=link.id,
                 symptom="lvl", status="open", opened_at=utcnow())
        sdb.add(c); sdb.commit()
        user = SimpleNamespace(username="t", role="engineer")
        change_status(c.id, status="escalated", link_state="", waiting_on="",
                      escalation_level="L2", user=user, db=sdb)
        assert sdb.get(Case, c.id).escalation_level == "L2"
        change_status(c.id, status="escalated", link_state="", waiting_on="",
                      escalation_level="Hacker", user=user, db=sdb)
        assert sdb.get(Case, c.id).escalation_level == "L2"  # junk ignored
    finally:
        sdb.close()

def test_import_page_not_swallowed_by_hid_route():
    """GET /handover/import must render, not 422 on {hid}='import'."""
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app, follow_redirects=False)
    r = c.post("/login", data={"username": "admin", "password": "elnoc-admin"})
    c.cookies.set("elnoc_session", r.cookies.get("elnoc_session"))
    r = c.get("/handover/import")
    assert r.status_code == 200 and "Paste today" in r.text

def test_import_apply_end_to_end():
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app, follow_redirects=False)
    r = c.post("/login", data={"username": "admin", "password": "elnoc-admin"})
    assert r.status_code == 303
    c.cookies.set("elnoc_session", r.cookies.get("elnoc_session"))
    text = ("TICKET UPDATES – 16/10/2026\nUNRESOLVED LINKS\n\n"
            "LTV8 Ikeja-RC\nSTATUS: DOWN\n"
            "UPDATE: FOLLOWING UP WITH OREGUN TEAM | far end still dark\n\n"
            "Brand New Fibre\nSTATUS: DOWN\nUPDATE: FOLLOWING UP WITH ISLAND TEAM\n")
    r = c.post("/handover/import", data={"raw_text": text, "shift_date": "16/10/2026"})
    assert r.status_code == 200 and "Preview" in r.text
    assert "LTV8 Ikeja-RC" in r.text and "NEW LINK" in r.text
    import re
    iid = int(re.search(r"/handover/import/(\d+)/apply", r.text).group(1))
    # apply: matched LTV8 applied, unknown link created via checkbox
    r = c.post(f"/handover/import/{iid}/apply",
               data={"newlink_1": "on"})
    assert r.status_code == 303 and "/handover/import/done/" in r.headers["location"]
    sdb = SessionLocal()
    try:
        ltv = sdb.query(Link).filter(Link.name == "LTV8 Ikeja-RC").first()
        ltv_case = sdb.query(Case).filter(
            Case.link_id == ltv.id, Case.status != "resolved")\
            .order_by(Case.opened_at.desc()).first()
        assert ltv_case.waiting_on == "OREGUN TEAM"
        assert any("Handover 16/10/2026" in e.text for e in sdb.query(CaseEvent)
                   .filter(CaseEvent.case_id == ltv_case.id).all())
        new = sdb.query(Link).filter(Link.name == "Brand New Fibre").first()
        assert new is not None
        assert "OREGUN TEAM" in (ltv_case.waiting_on or "")
    finally:
        sdb.close()
