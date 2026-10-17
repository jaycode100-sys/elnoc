"""Phoenix CSV import (FR-04, FR-10). Committed path: CSV first, API later."""
from __future__ import annotations
import csv
from sqlalchemy.orm import Session
from ..models import Customer, Link, Contact, SiteDevice, ContactChannel, LinkContact

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
            elif kind == "channels":
                # contact_id/name + channel,value,label -> how we reach them
                contact = None
                if (row.get("contact_id") or "").strip().isdigit():
                    contact = db.get(Contact, int(row["contact_id"]))
                if contact is None and (row.get("contact") or "").strip():
                    contact = db.query(Contact).filter(
                        Contact.name == row["contact"].strip()).first()
                if contact is None:
                    continue
                ch = (row.get("channel") or "whatsapp").strip().lower()
                val = (row.get("value") or "").strip()
                lab = (row.get("label") or "").strip()
                if not val:
                    # fall back to the flat contact columns
                    val = {"whatsapp": contact.whatsapp_number,
                           "email": contact.email,
                           "phone": contact.phone}.get(ch, "")
                if not val:
                    continue
                dup = db.query(ContactChannel).filter(
                    ContactChannel.contact_id == contact.id,
                    ContactChannel.channel == ch,
                    ContactChannel.value == val).first()
                if not dup:
                    db.add(ContactChannel(contact_id=contact.id, channel=ch,
                                          value=val[:300], label=lab[:200],
                                          note=row.get("note", "")[:400],
                                          is_primary=str(row.get("primary", "")).lower()
                                          in ("1", "y", "yes", "true")))
                n += 1
            elif kind == "link_contacts":
                link = db.query(Link).filter(
                    Link.name == (row.get("link") or "").strip()).first()
                if not link:
                    continue
                contact = None
                if (row.get("contact_id") or "").strip().isdigit():
                    contact = db.get(Contact, int(row["contact_id"]))
                if contact is None and (row.get("contact") or "").strip():
                    contact = db.query(Contact).filter(
                        Contact.name == row["contact"].strip()).first()
                if contact is None:
                    continue
                primary = str(row.get("primary", "")).lower() in ("1", "y", "yes", "true")
                if primary:
                    for lc in db.query(LinkContact).filter(
                            LinkContact.link_id == link.id).all():
                        lc.is_primary = False
                exists = db.query(LinkContact).filter(
                    LinkContact.link_id == link.id,
                    LinkContact.contact_id == contact.id).first()
                if exists:
                    exists.role = row.get("role", exists.role) or exists.role
                    exists.combo_note = row.get("combo_note", exists.combo_note) or exists.combo_note
                    exists.is_primary = primary or exists.is_primary
                else:
                    db.add(LinkContact(link_id=link.id, contact_id=contact.id,
                                       role=(row.get("role") or "contact").strip(),
                                       combo_note=(row.get("combo_note") or "")[:300],
                                       is_primary=primary))
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
