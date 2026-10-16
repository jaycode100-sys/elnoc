"""Phoenix CSV import (FR-04, FR-10). Committed path: CSV first, API later."""
from __future__ import annotations
import csv
from sqlalchemy.orm import Session
from ..models import Customer, Link, Contact, SiteDevice

def import_registry_csv(db: Session, kind: str, path: str) -> int:
    """kind in customers|links|contacts. Returns rows imported."""
    n = 0
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if kind == "customers":
                name = (row.get("name") or "").strip()
                if not name:
                    continue
                c = db.query(Customer).filter(Customer.name == name).first()
                if not c:
                    c = Customer(name=name)
                    db.add(c)
                c.aliases = row.get("aliases", c.aliases or "")
                c.tier = row.get("tier", c.tier or "standard")
                c.notes = row.get("notes", c.notes or "")
                c.sources = row.get("sources", c.sources or "PRTG")
                n += 1
            elif kind == "links":
                name = (row.get("name") or "").strip()
                if not name:
                    continue
                cust = db.query(Customer).filter(
                    Customer.name == (row.get("customer") or "").strip()).first()
                if not cust:
                    cust = Customer(name=(row.get("customer") or "Unknown").strip() or "Unknown")
                    db.add(cust); db.flush()
                l = db.query(Link).filter(Link.name == name).first()
                if not l:
                    l = Link(name=name, customer_id=cust.id)
                    db.add(l)
                l.customer_id = cust.id
                l.circuit_id = row.get("circuit_id", l.circuit_id or "")
                l.a_end = row.get("a_end", l.a_end or "")
                l.b_end = row.get("b_end", l.b_end or "")
                l.medium = row.get("medium", l.medium or "fibre")
                l.responsible_team = row.get("responsible_team", l.responsible_team or "")
                l.aliases = row.get("aliases", l.aliases or "")
                l.tier = row.get("tier", l.tier or "access")
                l.sources = row.get("sources", l.sources or "PRTG")
                if row.get("primary_contact"):
                    ct = db.query(Contact).filter(Contact.name == row["primary_contact"].strip()).first()
                    if ct:
                        l.primary_contact_id = ct.id
                n += 1
            elif kind == "contacts":
                name = (row.get("name") or "").strip()
                if not name:
                    continue
                c = db.query(Contact).filter(Contact.name == name).first()
                if not c:
                    c = Contact(name=name)
                    db.add(c)
                c.role = row.get("role", c.role or "")
                c.team = row.get("team", c.team or "")
                c.phone = row.get("phone", c.phone or "")
                c.email = row.get("email", c.email or "")
                c.whatsapp_number = row.get("whatsapp_number", c.whatsapp_number or "")
                c.preferred_channels = row.get("preferred_channels", c.preferred_channels or "email,whatsapp")
                c.availability_hours = row.get("availability_hours", c.availability_hours or "")
                n += 1
            elif kind == "devices":
                # Sensor/host → link map: hostname must match the PRTG device or
                # Zabbix host name exactly (case-insensitive). Re-import to update.
                host = (row.get("hostname") or "").strip()
                if not host:
                    continue
                d = db.query(SiteDevice).filter(SiteDevice.hostname == host).first()
                if not d:
                    d = SiteDevice(hostname=host)
                    db.add(d)
                d.ip = row.get("ip", d.ip or "")
                d.site = row.get("site", d.site or "")
                try:
                    d.latitude = float(row["latitude"]) if row.get("latitude") else d.latitude
                    d.longitude = float(row["longitude"]) if row.get("longitude") else d.longitude
                except ValueError:
                    pass
                d.criticality_tier = row.get("tier", d.criticality_tier or "access")
                d.monitored_in = row.get("monitored_in", d.monitored_in or "PRTG")
                if row.get("link"):
                    link = db.query(Link).filter(Link.name == row["link"].strip()).first()
                    if link:
                        d.link_id = link.id
                n += 1
    db.commit()
    return n
