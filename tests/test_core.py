"""14.1: fuzzy matching, alias learning, similar ranking, stale-wait, handover, secrets."""
from datetime import timedelta
from tests.conftest import fresh_db
from app.services.search import search_links, learn_alias
from app.services.similar import similar_cases
from app.services.handover import build_handover_text
from app.services.escalation import is_stale_wait
from app.security import find_secret
from app.models import Case, Link
from app.utils_time import utcnow

db = fresh_db()

def test_fuzzy_ltv8_ranks_first():
    res = search_links(db, "ltv8 ikeja")
    assert res, "no results"
    assert res[0]["link_name"] == "LTV8 Ikeja-RC", res[0]

def test_alias_learning_boosts():
    # learn a shorthand repeatedly, then it must outrank rivals
    link = db.query(Link).filter(Link.name == "Demo Bank HQ").first()
    for _ in range(4):
        learn_alias(db, "dbhq", "link", link.id)
    res = search_links(db, "dbhq")
    assert res[0]["link_id"] == link.id, res[:3]

def test_similar_same_link_first():
    ltv = db.query(Link).filter(Link.name == "LTV8 Ikeja-RC").first()
    probe = Case(link_id=ltv.id, customer_id=ltv.customer_id,
                 symptom="far end not transmitting, rsl low", opened_at=utcnow())
    db.add(probe); db.flush()
    sims = similar_cases(db, probe)
    assert sims, "expected similar cases"
    assert sims[0].link_id == ltv.id
    db.rollback()

def test_stale_wait_exact_boundary():
    from app.config import settings
    c = Case(status="waiting_other_team", link_state="down",
             opened_at=utcnow() - timedelta(minutes=settings.STALE_WAIT_MIN + 5),
             waiting_on="OREGUN TEAM")
    assert is_stale_wait(c) is True
    c2 = Case(status="waiting_other_team", link_state="down",
              opened_at=utcnow() - timedelta(minutes=5), waiting_on="OREGUN TEAM")
    assert is_stale_wait(c2) is False
    c3 = Case(status="open", link_state="down", opened_at=utcnow() - timedelta(hours=9))
    assert is_stale_wait(c3) is False

def test_handover_exact_format():
    c1 = Case(id=101, status="waiting_other_team", link_state="down",
              waiting_on="OREGUN TEAM", symptom="x", opened_at=utcnow())
    c1._link_name = "LTV8 Ikeja-RC"; c1._latest_note = "far end dark"; c1._affected = []
    c2 = Case(id=102, status="open", link_state="degraded", waiting_on="",
              symptom="flap", opened_at=utcnow())
    c2._link_name = "Demo Bank HQ"; c2._latest_note = "flapping"; c2._affected = ["LTV8 Backup"]
    c3 = Case(id=103, status="resolved", link_state="up", waiting_on="", symptom="x",
              opened_at=utcnow())
    c3._link_name = "Prec Pearl Main"; c3._latest_note = ""; c3._affected = []
    text = build_handover_text([c1, c2, c3], "11/10/2026")
    assert text.startswith("TICKET UPDATES \u2013 11/10/2026")
    assert "UNRESOLVED LINKS" in text and "RESOLVED LINKS" in text
    assert "LTV8 IKEJA-RC\nSTATUS: DOWN\nUPDATE: FOLLOWING UP WITH OREGUN TEAM | far end dark" in text
    assert "LINKS AFFECTED\nLTV8 BACKUP" in text
    assert "PREC PEARL MAIN\nSTATUS: UP" in text
    assert "-------------------------------------------------" in text

def test_secret_block():
    assert find_secret("password: hunter2") is not None
    assert find_secret("snmp community: public123") is not None
    assert find_secret("api_key= ABC123XYZ") is not None
    assert find_secret("far end not transmitting, rsl -29dbm") is None
