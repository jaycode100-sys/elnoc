"""Desktop pane contract + quicklog issue/escalation-time API."""
import importlib.util
import json
import py_compile
from types import SimpleNamespace

import pytest

from tests.conftest import fresh_db  # noqa: F401  (ensures seeded test DB)
from app.database import SessionLocal
from app.models import Case, CaseEvent, Link
from app.routers.quicklog import api_quicklog

PANE_PATH = "client/ELNOC_Pane.py"

def _pane():
    spec = importlib.util.spec_from_file_location("elnoc_pane", PANE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def test_pane_compiles_and_imports_headless():
    py_compile.compile(PANE_PATH, doraise=True)
    mod = _pane()  # must not require tkinter / a display at import
    assert hasattr(mod, "PaneClient") and hasattr(mod, "build_payload")

def test_payload_contract():
    mod = _pane()
    p = mod.build_payload(link_id=3, device=" PuTTY 10.0.0.1 ", symptom=" far end dark ",
                          severity="critical", typed_query="ltv8",
                          issue_detected_at="2026-10-12T04:09")
    assert p["link_id"] == 3 and p["device"] == "PuTTY 10.0.0.1"
    assert p["symptom"] == "far end dark" and p["severity"] == "critical"
    assert p["issue_detected_at"] == "2026-10-12T04:09"
    assert mod.now_local_iso()[10] == "T"

def test_client_reports_unreachable_cleanly():
    mod = _pane()
    c = mod.PaneClient("http://127.0.0.1:9", timeout=2)
    with pytest.raises(mod.PaneError):
        c.search("ltv8")

def test_quicklog_issue_and_escalation_time():
    db = SessionLocal()  # reuse seeded file; re-wiping locks it on Windows
    try:
        user = SimpleNamespace(username="pane-tester")
        link = db.query(Link).filter(Link.name == "LTV8 Ikeja-RC").first()
        r = api_quicklog(None, {"link_id": link.id, "device": "PuTTY x",
                                "symptom": "pane test far end",
                                "typed_query": "ltv8 ikeja",
                                "issue_detected_at": "2026-10-12T04:09"}, db, user)
        assert r.status_code == 200, r.body
        doc = json.loads(r.body)
        assert doc["escalation_time"].endswith("WAT")  # system-managed stamp
        assert f"ELNOC case #{doc['case_id']}" in doc["phoenix_text"]  # copy-ready text
        notes = [e.text for e in db.query(CaseEvent)
                 .filter(CaseEvent.case_id == doc["case_id"]).all()]
        assert any("Issue detected (engineer-reported)" in t for t in notes)
        case = db.get(Case, doc["case_id"])
        assert case.opened_by == "manual" and case.engineer == "pane-tester"
    finally:
        db.close()

def test_quicklog_bad_issue_rejected():
    db = SessionLocal()
    try:
        user = SimpleNamespace(username="pane-tester")
        link = db.query(Link).first()
        r = api_quicklog(None, {"link_id": link.id, "device": "d",
                                "symptom": "x", "issue_detected_at": "not-a-date"},
                         db, user)
        assert r.status_code == 400
    finally:
        db.close()
