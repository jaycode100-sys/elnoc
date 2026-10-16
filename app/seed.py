"""Seed data: contacts from handover sample + 10 cases incl. 14h LTV8 Ikeja-RC (sec 4.3)."""
from __future__ import annotations
from datetime import timedelta
from sqlalchemy.orm import Session
from .models import Customer, Contact, Link, EscalationRule, Case, CaseEvent
from .utils_time import utcnow
from .security import hash_password
from .models import AppUser

def seed_all(db: Session) -> dict:
    out = {"users": 0, "contacts": 0, "customers": 0, "links": 0, "cases": 0}
    # users
    defaults = [("admin", "Admin", "admin", "elnoc-admin"),
                ("day1", "Day Engineer", "engineer", "elnoc-day1"),
                ("night1", "Night Engineer", "engineer", "elnoc-night1"),
                ("senior1", "Senior Engineer", "senior", "elnoc-senior1")]
    for uname, name, role, pw in defaults:
        if not db.query(AppUser).filter(AppUser.username == uname).first():
            h, s = hash_password(pw)
            db.add(AppUser(username=uname, name=name, role=role, active=True,
                           password_hash=h, password_salt=s))
            out["users"] += 1
    # contacts (from handover sample: Oregun team, Mr Adekunle, Yomi, Prec Pearl, Levene Lcon)
    contacts = [
        ("Mr Adekunle", "Escalation", "Oregun", "+2348000000001", "adekunle@company.local"),
        ("Oregun NOC", "Team", "Oregun", "+2348000000002", "oregun@company.local"),
        ("Yomi", "Field", "Field", "+2348000000003", "yomi@company.local"),
        ("Prec Pearl NOC", "Team", "Prec Pearl", "+2348000000004", "precpearl@company.local"),
        ("Levene Lcon", "Partner", "Levene", "+2348000000005", "levene@company.local"),
        ("Line Manager", "Manager", "NOC", "+2348000000006", "manager@company.local"),
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
    # customers + links
    cust_links = [
        ("LTV8", [("LTV8 Ikeja-RC", "LTV8-001", "Ikeja", "RC", "core", "ltv8 ikeja rc"),
                  ("LTV8 Backup", "LTV8-002", "Ikeja", "Backup", "access", "ltv8 backup")]),
        ("Prec Pearl", [("Prec Pearl Main", "PP-001", "HQ", "Branch", "distribution", "prec pearl")]),
        ("Levene", [("Levene Lcon Main", "LV-001", "Lagos", "Lcon", "access", "levene lcon")]),
        ("Demo Bank", [("Demo Bank HQ", "DB-001", "Marina", "HQ", "distribution", "demo bank")]),
    ]
    lmap = {}
    for cname, links in cust_links:
        cust = db.query(Customer).filter(Customer.name == cname).first()
        if not cust:
            cust = Customer(name=cname, aliases=cname.lower(), sources="PRTG,ZABBIX,SMARTOLT,PHOENIX")
            db.add(cust); db.flush()
            out["customers"] += 1
        for lname, circ, a, b, tier, alias in links:
            l = db.query(Link).filter(Link.name == lname).first()
            if not l:
                prim = cmap.get("Line Manager")
                l = Link(name=lname, customer_id=cust.id, circuit_id=circ, a_end=a, b_end=b,
                         responsible_team="NOC", aliases=alias, tier=tier, sources="PRTG,ZABBIX",
                         primary_contact_id=prim.id if prim else None,
                         optic_a="GPON-C+", optic_b="GPON-C+")
                db.add(l); db.flush()
                out["links"] += 1
            lmap[lname] = l
    # escalation rules: 3 steps fit in 1h MTTA (15 min each)
    for lname, l in lmap.items():
        if db.query(EscalationRule).filter(EscalationRule.link_id == l.id).first():
            continue
        steps = [("Line Manager", 15), ("Oregun NOC", 15), ("Mr Adekunle", 15)]
        for i, (cname, wait) in enumerate(steps, 1):
            db.add(EscalationRule(link_id=l.id, step_order=i,
                                  contact_id=cmap[cname].id, wait_minutes=wait,
                                  channels="email,whatsapp"))
    db.commit()
    # 10 seed cases incl. the 14-hour LTV8 case
    if db.query(Case).count() == 0:
        ltv = lmap["LTV8 Ikeja-RC"]
        cust_id = ltv.customer_id
        now = utcnow()
        seeds = [
            dict(link=ltv, symptom="Far end not transmitting; RSL low on local (-29 dBm)",
                 checks="Checked local TX, RSL transceiver detail showed far-end dark",
                 cat="far-end not transmitting", fix="Oregun re-seated far-end SFP; RSL back to -21 dBm",
                 first="Check RSL transceiver detail first", hours_ago=72, dur=14 * 60,
                 waiting="OREGUN TEAM", helped="Mr Adekunle", state="up", status="resolved"),
        ]
        for i in range(2, 11):
            l = list(lmap.values())[i % len(lmap)]
            seeds.append(dict(link=l, symptom=f"Seed case {i}: link flapped, monitoring down 10 min",
                              checks="Pinged A-end, checked PRTG", cat="fibre cut" if i % 3 == 0 else "power",
                              fix="Restored after field check", first="Ping A-end first",
                              hours_ago=i * 9, dur=45 + i * 7, waiting="", helped="",
                              state="up", status="resolved"))
        for s in seeds:
            opened = now - timedelta(hours=s["hours_ago"])
            c = Case(engineer="day1", customer_id=s["link"].customer_id, link_id=s["link"].id,
                     device=s["link"].a_end, symptom=s["symptom"], checks_done=s["checks"],
                     root_cause_category=s["cat"], root_cause_detail=s["checks"],
                     fix=s["fix"], first_thing_to_check_next_time=s["first"],
                     status=s["status"], severity="critical", opened_by="manual",
                     opened_at=opened, closed_at=opened + timedelta(minutes=s["dur"]),
                     time_to_resolve_min=s["dur"], link_state=s["state"],
                     waiting_on=s["waiting"], helped_by=s["helped"],
                     escalated_to=s["waiting"])
            db.add(c); db.flush()
            db.add(CaseEvent(case_id=c.id, at=opened, engineer="day1", kind="note", text=s["symptom"]))
            db.add(CaseEvent(case_id=c.id, at=opened + timedelta(minutes=s["dur"]), engineer="day1",
                             kind="status", text=f"Resolved: {s['fix']}"))
            out["cases"] += 1
        # one live open + one waiting case for dashboard/handover demo
        l2 = lmap["Prec Pearl Main"]
        c = Case(engineer="night1", customer_id=l2.customer_id, link_id=l2.id, device=l2.a_end,
                 symptom="Link down per PRTG; awaiting Prec Pearl team", severity="critical",
                 status="waiting_other_team", link_state="down", waiting_on="PREC PEARL TEAM",
                 opened_at=now - timedelta(minutes=150), opened_by="auto")
        db.add(c); db.flush()
        db.add(CaseEvent(case_id=c.id, at=c.opened_at, engineer="system", kind="system",
                         text="Auto-opened from PRTG: Sensor DOWN"))
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
