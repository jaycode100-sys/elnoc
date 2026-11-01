"""Seed data: contacts + sample cases for demo purposes.
No default users or passwords are created. The first user must be created
through the signup flow (restricted by ADMIN_EMAIL_DOMAINS env var, if set).
"""
from __future__ import annotations

from datetime import timedelta
from sqlalchemy.orm import Session

from .models import Customer, Contact, Link, EscalationRule, Case, CaseEvent
from .utils_time import utcnow


def seed_all(db: Session) -> dict:
    out = {"users": 0, "contacts": 0, "customers": 0, "links": 0, "cases": 0}
    # NO default users or passwords are seeded.
    # Contacts use synthetic data only — no real phone numbers or emails.
    contacts = [
        ("Oregun NOC", "Team", "Oregun", "+234-800-000-0001", "oregun.noc@example.invalid"),
        ("Prec Pearl NOC", "Team", "Prec Pearl", "+234-800-000-0002", "precpearl.noc@example.invalid"),
        ("Line Manager", "Manager", "NOC", "+234-800-000-0003", "line.manager@example.invalid"),
    ]
    cmap = {}
    for name, role, team, phone, email in contacts:
        c = db.query(Contact).filter(Contact.name == name).first()
        if not c:
            c = Contact(name=name, role=role, team=team, phone=phone, email=email,
                        whatsapp_number=phone, preferred_channels="email,whatsapp")
            db.add(c); db.flush()
            out["contacts"] += 1
        cmap[name] = c
    # customers + links (synthetic)
    cust_links = [
        ("LTV8", [("LTV8 Ikeja-RC", "LTV8-001", "Ikeja", "RC", "core"),
                  ("LTV8 Backup", "LTV8-002", "Ikeja", "Backup", "access")]),
        ("Prec Pearl", [("Prec Pearl Main", "PP-001", "HQ", "Branch", "distribution")]),
        ("Levene", [("Levene Lcon Main", "LV-001", "Lagos", "Lcon", "access")]),
        ("Demo Bank", [("Demo Bank HQ", "DB-001", "Marina", "HQ", "distribution")]),
    ]
    lmap = {}
    for cname, links in cust_links:
        cust = db.query(Customer).filter(Customer.name == cname).first()
        if not cust:
            cust = Customer(name=cname, aliases=cname.lower(), sources="PRTG,ZABBIX,SMARTOLT,PHOENIX")
            db.add(cust); db.flush()
            out["customers"] += 1
        for lname, circ, a, b, tier in links:
            l = db.query(Link).filter(Link.name == lname).first()
            if not l:
                prim = cmap.get("Line Manager")
                l = Link(name=lname, customer_id=cust.id, circuit_id=circ, a_end=a, b_end=b,
                         responsible_team="NOC", tier=tier, sources="PRTG,ZABBIX",
                         primary_contact_id=prim.id if prim else None,
                         optic_a="GPON-C+", optic_b="GPON-C+")
                db.add(l); db.flush()
                out["links"] += 1
            lmap[lname] = l
    # escalation rules
    for lname, l in lmap.items():
        if db.query(EscalationRule).filter(EscalationRule.link_id == l.id).first():
            continue
        steps = [("Line Manager", 15), ("Oregun NOC", 15)]
        for i, (cname, wait) in enumerate(steps, 1):
            db.add(EscalationRule(link_id=l.id, step_order=i,
                                  contact_id=cmap[cname].id, wait_minutes=wait,
                                  channels="email,whatsapp"))
    db.commit()
    # 3 seed cases (synthetic, resolved)
    if db.query(Case).count() == 0:
        now = utcnow()
        seeds = [
            dict(link=lmap["LTV8 Ikeja-RC"],
                 symptom="Far end not transmitting; RSL low on local",
                 cat="far-end not transmitting", fix="Re-seated far-end SFP; RSL restored",
                 first="Check RSL transceiver detail first", hours_ago=72, dur=14 * 60,
                 waiting="OREGUN TEAM", state="up", status="resolved"),
            dict(link=list(lmap.values())[1],
                 symptom="Link flapped, monitoring down",
                 cat="fibre cut", fix="Restored after field check",
                 first="Ping A-end first", hours_ago=36, dur=45,
                 waiting="", state="up", status="resolved"),
            dict(link=list(lmap.values())[2],
                 symptom="Link flapped, monitoring down",
                 cat="power", fix="Restored after field check",
                 first="Ping A-end first", hours_ago=18, dur=52,
                 waiting="", state="up", status="resolved"),
        ]
        for s in seeds:
            opened = now - timedelta(hours=s["hours_ago"])
            c = Case(engineer="system", customer_id=s["link"].customer_id, link_id=s["link"].id,
                     device=s["link"].a_end, symptom=s["symptom"],
                     checks_done=s["fix"], root_cause_category=s["cat"],
                     root_cause_detail=s["fix"], fix=s["fix"],
                     first_thing_to_check_next_time=s["first"],
                     status=s["status"], severity="major", opened_by="seed",
                     opened_at=opened, closed_at=opened + timedelta(minutes=s["dur"]),
                     time_to_resolve_min=s["dur"], link_state=s["state"],
                     waiting_on=s["waiting"], helped_by="",
                     escalated_to="")
            db.add(c); db.flush()
            db.add(CaseEvent(case_id=c.id, at=opened, engineer="system", kind="note",
                             text=s["symptom"]))
            db.add(CaseEvent(case_id=c.id, at=opened + timedelta(minutes=s["dur"]),
                             engineer="system", kind="status",
                             text=f"Resolved: {s['fix']}"))
            out["cases"] += 1
        db.commit()
        # sync FTS
        from sqlalchemy import text as _t
        for c in db.query(Case).all():
            link = db.get(Link, c.link_id) if c.link_id else None
            cust = db.get(Customer, c.customer_id) if c.customer_id else None
            db.execute(_t("INSERT OR IGNORE INTO case_fts(case_id, symptom, fix, root_cause_detail, customer_name, link_name)"
                          " VALUES (:cid,:s,:f,:r,:c,:l)"),
                       {"cid": c.id, "s": c.symptom or "", "f": c.fix or "",
                        "r": c.root_cause_detail or "",
                        "c": cust.name if cust else "", "l": link.name if link else ""})
        db.commit()
    return out
