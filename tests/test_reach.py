"""MORE INFO reachability: channels, combos, primary contact, escalation chain."""
from tests.conftest import fresh_db
from app.database import SessionLocal
from app.models import Contact, Link, ContactChannel, LinkContact, REACH_CHANNELS
from app.services.contacts import (reach_summary, compact_reach, channels_line,
                                   contact_card)
from app.utils_time import utcnow

db = fresh_db()  # one seeded DB per module (re-wiping mid-module locks on Windows)


def test_channels_line_combines_channels():
    db.rollback()
    c = Contact(name="Test Person", team="Oregun")
    db.add(c); db.flush()
    db.add(ContactChannel(contact_id=c.id, channel="whatsapp",
                          value="+2348000000001", label="personal"))
    db.add(ContactChannel(contact_id=c.id, channel="whatsapp_group",
                          value="Oregun-NOC", label="group"))
    db.add(ContactChannel(contact_id=c.id, channel="email",
                          value="a@b.c", label="work"))
    db.commit()
    line = channels_line(db, c)
    assert "WhatsApp (direct number)" in line
    assert "WhatsApp group" in line
    assert "Email" in line
    assert line.count("+") == 2  # three channels joined by two '+'


def test_channel_summary_counts_repeats():
    db.rollback()
    c = Contact(name="Two Numbers")
    db.add(c); db.flush()
    db.add(ContactChannel(contact_id=c.id, channel="whatsapp", value="+1"))
    db.add(ContactChannel(contact_id=c.id, channel="whatsapp", value="+2"))
    db.commit()
    assert "WhatsApp (direct number) (2)" in channels_line(db, c)


def test_no_channels_falls_back_to_flat_fields():
    db.rollback()
    c = Contact(name="Flat Only", whatsapp_number="+2341", email="x@y.z")
    db.add(c); db.commit()
    assert "WhatsApp 1" in channels_line(db, c)
    assert "Email 1" in channels_line(db, c)


def test_link_summary_finds_primary_and_chain():
    db.rollback()
    link = db.query(Link).filter(Link.name == "LTV8 Ikeja-RC").first()
    line = db.query(Link).filter(Link.name == "LTV8 Backup").first()
    mgr = db.query(Contact).filter(Contact.name == "Line Manager").first()
    yomi = db.query(Contact).filter(Contact.name == "Yomi").first()
    if not db.query(ContactChannel).filter(ContactChannel.contact_id == mgr.id).first():
        db.add(ContactChannel(contact_id=mgr.id, channel="whatsapp", value="+2348000000006"))
    if not db.query(LinkContact).filter(LinkContact.link_id == link.id).first():
        db.add(LinkContact(link_id=link.id, contact_id=mgr.id, role="primary",
                           is_primary=True, combo_note="WhatsApp first"))
        db.add(LinkContact(link_id=link.id, contact_id=yomi.id, role="field"))
    db.commit()
    s = reach_summary(db, link)
    assert s["any_reach"] is True
    assert s["primary"]["name"] == "Line Manager"
    assert "WhatsApp first" in s["primary"]["combo_note"]
    assert len(s["contacts"]) >= 2
    assert s["chain"], "escalation chain should be read for the link"
    assert any(c["contact"]["name"] == "Line Manager" for c in s["chain"])
    assert "Line Manager" in compact_reach(db, link)


def test_link_without_contacts_says_so():
    db.rollback()
    link = db.query(Link).filter(Link.name == "Levene Lcon Main").first()
    s = reach_summary(db, link)
    if not s["any_reach"]:
        assert "NO CONTACT ON FILE" in s["headline"]
        assert compact_reach(db, link) in ("NO CONTACT ON FILE", s["headline"])


def test_reach_kinds_collected():
    db.rollback()
    link = db.query(Link).first()
    mgr = db.query(Contact).first()
    db.add(ContactChannel(contact_id=mgr.id, channel="whatsapp", value="+1"))
    db.add(ContactChannel(contact_id=mgr.id, channel="email", value="a@b.c"))
    db.add(LinkContact(link_id=link.id, contact_id=mgr.id, role="primary",
                       is_primary=True))
    db.commit()
    s = reach_summary(db, link)
    assert set(s["kinds"]) >= {"whatsapp", "email"}


def test_channels_csv_and_link_contacts_import(tmp_path):
    from app.adapters.phoenix_csv import import_registry_csv
    db = SessionLocal()
    try:
        f = tmp_path / "ch.csv"
        f.write_text("contact,channel,value,label\n"
                     "Yomi,whatsapp,+2348000000003,field phone\n"
                     "Yomi,whatsapp_group,Field-NOC,field group\n")
        n = import_registry_csv(db, "channels", str(f))
        assert n == 2
        yomi = db.query(Contact).filter(Contact.name == "Yomi").first()
        assert db.query(ContactChannel).filter(
            ContactChannel.contact_id == yomi.id).count() == 2

        g = tmp_path / "lc.csv"
        g.write_text("link,contact,role,combo_note,primary\n"
                     "Levene Lcon Main,Levene Lcon,partner,WhatsApp partner,y\n")
        n2 = import_registry_csv(db, "link_contacts", str(g))
        assert n2 == 1
        link = db.query(Link).filter(Link.name == "Levene Lcon Main").first()
        s = reach_summary(db, link)
        assert s["primary"]["name"] == "Levene Lcon"
    finally:
        db.close()


def test_case_page_shows_reach_line():
    db.rollback()
    import re
    from fastapi.testclient import TestClient
    from app.database import init_db
    init_db()
    from app.main import app
    c = TestClient(app, follow_redirects=False)
    uname = "reach" + __import__("uuid").uuid4().hex[:6]
    r = c.post("/signup", data={"username": uname, "name": "r",
                                "password": "reachpass-12", "password2": "reachpass-12"})
    assert r.status_code == 303
    c.cookies.set("elnoc_session", r.cookies.get("elnoc_session"))
    ids = re.findall(r"/cases/(\d+)", c.get("/cases").text)
    assert ids
    page = c.get(f"/cases/{ids[0]}")
    assert page.status_code == 200
    assert "How we reach this client" in page.text
    assert "MORE INFO" in page.text