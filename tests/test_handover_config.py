"""Configured handover format (MCQ answers), state classifier, gate, evidence."""
from datetime import timedelta

from tests.conftest import fresh_db
from app.database import SessionLocal
from app.models import (Case, CaseEvent, Link, Attachment, EVIDENCE_KINDS,
                        level_label, AuditLog)
from app.services.handover import (build_handover_text, build_summary, fmt_dur,
                                   outage_minutes, _state)
from app.services import link_state as ls
from app.services import handover_gate as gate
from app.utils_time import utcnow

db = fresh_db()


def _mk(link, state, waiting="", sym="", ticket="", fixed_h=None, fix="",
        lvl="", age_h=5, n_party=True):
    c = Case(engineer="t", customer_id=link.customer_id, link_id=link.id,
             symptom=sym or "fault", status="open", severity="critical",
             link_state=state, waiting_on=waiting, escalation_level=lvl,
             phoenix_ticket_no=ticket, opened_at=utcnow() - timedelta(hours=age_h),
             fix=fix)
    if fixed_h is not None:
        c.restored_at = utcnow() - timedelta(hours=fixed_h)
    db.add(c); db.flush()
    c._link_name = link.name; c._latest_note = sym; c._affected = []
    if not n_party:
        c.waiting_on = ""
    return c


# ---------- format ----------
def test_header_has_date_and_time():
    link = db.query(Link).first()
    c = _mk(link, "down")
    text = build_handover_text([c], "16/10/2026", summary=False)
    assert text.startswith("NOC HANDOVER \u2013 16/10/2026")
    assert "WAT" in text.splitlines()[0]
    db.rollback()


def test_summary_comes_before_unresolved():
    link = db.query(Link).first()
    c = _mk(link, "down")
    text = build_handover_text([c], "16/10/2026")
    assert text.index("SHIFT SUMMARY") < text.index("UNRESOLVED LINKS")
    db.rollback()


def test_state_subheaders_split_unresolved():
    links = db.query(Link).all()
    d = _mk(links[0], "down", waiting="OREGUN TEAM")
    g = _mk(links[1], "degraded", waiting="PREC PEARL TEAM")
    u = _mk(links[2], "unstable", waiting="ISLAND TEAM")
    text = build_handover_text([d, g, u], "16/10/2026", summary=False)
    assert "DOWN (1)" in text and "DEGRADED (1)" in text and "UNSTABLE (1)" in text
    assert text.index("DOWN (1)") < text.index("DEGRADED (1)") < text.index("UNSTABLE (1)")
    db.rollback()


def test_duration_beside_each_incident_long_form():
    link = db.query(Link).first()
    c = _mk(link, "down", waiting="OREGUN TEAM", age_h=5)
    text = build_handover_text([c], "16/10/2026", summary=False)
    assert "5H 0M" in text
    assert fmt_dur(45) == "45M" and fmt_dur(192) == "3H 12M"
    db.rollback()


def test_note_line_replaces_the_bar():
    link = db.query(Link).first()
    c = _mk(link, "down", waiting="OREGUN TEAM", sym="far end dark, RSL -29")
    text = build_handover_text([c], "16/10/2026", summary=False)
    assert "UPDATE: FOLLOWING UP WITH OREGUN TEAM" in text
    assert "NOTE: far end dark" in text
    assert " | far end dark" not in text  # no bar carrying the second fact
    db.rollback()


def test_level_shown_in_words():
    link = db.query(Link).first()
    c = _mk(link, "down", waiting="X", lvl="L2")
    text = build_handover_text([c], "16/10/2026", summary=False)
    assert "LEVEL: L2 (advanced technical)" in text
    assert level_label("Vendor") == "Vendor (third-party)"
    db.rollback()


def test_no_party_is_called_out_loudly():
    link = db.query(Link).first()
    c = _mk(link, "down", n_party=False)
    text = build_handover_text([c], "16/10/2026", summary=False)
    assert "NO PARTY NAMED" in text and "ESCALATE NOW" in text
    db.rollback()


def test_divider_only_before_summary():
    link = db.query(Link).first()
    a = _mk(link, "down", waiting="X")
    b = _mk(link, "degraded", waiting="Y")
    text = build_handover_text([a, b], "16/10/2026", summary=True)
    assert text.count("-------------------------------------------------") == 1
    text2 = build_handover_text([a, b], "16/10/2026", summary=False)
    assert text2.count("-------------------------------------------------") == 0
    db.rollback()


def test_stale_flag_on_by_default_in_text():
    link = db.query(Link).first()
    c = _mk(link, "down", waiting="X")
    text = build_handover_text([c], "16/10/2026", summary=False,
                               stale_map={c.id: "SAME UPDATE 18H"})
    assert "SAME UPDATE 18H" in text
    db.rollback()


def test_ticket_still_never_leaks():
    link = db.query(Link).first()
    c = _mk(link, "down", waiting="X", ticket="PHX-4821")
    text = build_handover_text([c], "16/10/2026", summary=True)
    assert "PHX-4821" not in text
    db.rollback()


def test_still_unresolved_line_has_state_level_age_party():
    link = db.query(Link).first()
    c = _mk(link, "unstable", waiting="ISLAND TEAM", lvl="L3", age_h=3)
    s = build_summary([c], "16/10/2026")
    assert "UNSTABLE — L3 (senior), 3H 0M" in s
    assert "WITH ISLAND TEAM" in s
    db.rollback()


# ---------- classifier ----------
def test_flapping_recommends_unstable():
    from app.models import Event
    link = db.query(Link).first()
    now = utcnow()
    for i, t in enumerate(("down", "up", "down", "up")):
        db.add(Event(key=f"flap-{link.id}-{i}", type=t, source="PRTG",
                     device=link.name, link_id=link.id, severity="critical",
                     occurred_at=now - timedelta(minutes=50 - i * 10)))
    db.flush()
    f = ls.flapping(db, link.id)
    assert f["flapping"] is True and f["changes"] >= 3
    assert ls.recommend(db, Case(link_id=link.id, link_state="up"))["recommended"] == "unstable"
    db.rollback()


def test_challenge_text_names_both_causes():
    txt = ls.challenge_text({"recommended": "unstable", "why": "3 changes"})
    assert "DEGRADED = link is UP but carrying errors/loss" in txt
    assert "UNSTABLE  = link is flapping" in txt
    assert "cannot decide this for you" in txt


def test_calm_link_has_no_clear_signal():
    link = db.query(Link).first()
    card = ls.challenge_card(ls.recommend(db, Case(link_id=link.id)))
    assert card["flapping"] is False
    assert "insufficient" in card["detail"] or card["recommended"] in ("degraded", "unstable")


# ---------- gate ----------
def test_gate_blocks_unticketed_down_case():
    link = db.query(Link).first()
    c = _mk(link, "down", waiting="X", age_h=2)  # no ticket, older than 30 min
    rep = gate.check(db, [c])
    assert rep["ok"] is False
    assert rep["blocks"][0]["reason"] == "no_phoenix_ticket"
    db.rollback()


def test_gate_allows_ticketed_or_fresh():
    link = db.query(Link).first()
    c1 = _mk(link, "down", waiting="X", ticket="PHX-1", age_h=5)
    c2 = _mk(link, "down", waiting="X", age_h=0.2)  # inside the 30-min window
    rep = gate.check(db, [c1, c2])
    assert rep["ok"] is True and rep["blocks"] == []
    db.rollback()


def test_gate_flags_missing_party():
    link = db.query(Link).first()
    c = _mk(link, "degraded", ticket="PHX-2", n_party=False)
    rep = gate.check(db, [c])
    assert rep["ok"] is True
    assert any(f["reason"] == "no_waiting_party" for f in rep["flags"])
    db.rollback()


def test_override_is_audited():
    link = db.query(Link).first()
    c = _mk(link, "down", waiting="X", age_h=3)
    rep = gate.apply_override(db, [c], "vendor fault, ticket next shift", "day1")
    assert rep["overridden"] is True
    row = db.query(AuditLog).filter(
        AuditLog.entity == "handover",
        AuditLog.entity_id == "override").first()
    assert row is not None and "vendor fault" in row.diff
    db.rollback()


# ---------- evidence thread ----------
def test_evidence_thread_orders_and_tags():
    link = db.query(Link).first()
    c = _mk(link, "down", waiting="X")
    from app.routers.evidence import thread_rows, next_seq, has_resolution_evidence
    assert next_seq(db, c.id) == 1
    db.add(Attachment(case_id=c.id, filename="site.jpg", stored_path="x",
                      sha256="a" * 64, uploaded_by="day1", evidence_kind="location"))
    db.add(Attachment(case_id=c.id, filename="trace.sor", stored_path="y",
                      sha256="b" * 64, uploaded_by="day1", evidence_kind="trace",
                      thread_seq=2))
    db.add(Attachment(case_id=c.id, filename="util.png", stored_path="z",
                      sha256="c" * 64, uploaded_by="night1",
                      evidence_kind="resolution", thread_seq=3,
                      is_resolution_evidence=True))
    db.commit()
    rows = thread_rows(db, c.id)
    assert [r.evidence_kind for r in rows] == ["location", "trace", "resolution"]
    assert has_resolution_evidence(db, c.id) is True
    assert "resolution" in EVIDENCE_KINDS and "prtg" in EVIDENCE_KINDS


def test_up_case_without_proof_is_challenged():
    from app.routers.evidence import outstanding_challenge
    link = db.query(Link).first()
    c = _mk(link, "up", fixed_h=1)
    ch = outstanding_challenge(db, c.id)
    assert ch is not None and "PRTG" in ch["message"]
    db.add(Attachment(case_id=c.id, filename="proof.png", stored_path="p",
                      sha256="d" * 64, uploaded_by="day1",
                      evidence_kind="prtg", is_resolution_evidence=True))
    db.commit()
    assert outstanding_challenge(db, c.id) is None
    db.rollback()


def test_down_case_is_not_challenged_for_proof():
    from app.routers.evidence import outstanding_challenge
    link = db.query(Link).first()
    c = _mk(link, "down", waiting="X")
    assert outstanding_challenge(db, c.id) is None
    db.rollback()


def test_challenge_stamp_and_chase_route():
    from types import SimpleNamespace
    from app.routers.cases import stamp_chase
    from app.routers.evidence import challenge_resolution
    sdb = SessionLocal()
    try:
        link = sdb.query(Link).first()
        c = Case(engineer="t", customer_id=link.customer_id, link_id=link.id,
                 symptom="x", status="open", link_state="down",
                 waiting_on="OREGUN TEAM", opened_at=utcnow())
        sdb.add(c); sdb.commit()
        u = SimpleNamespace(username="day1", role="engineer")
        challenge_resolution(c.id, user=u, db=sdb)
        stamp_chase(c.id, user=u, db=sdb)
        got = sdb.get(Case, c.id)
        assert got.resolution_challenged_at is not None
        assert got.last_contact_attempt_at is not None
    finally:
        sdb.close()