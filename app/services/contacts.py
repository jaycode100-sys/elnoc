"""How do we reach the client on this link? (MORE INFO)

Answers the question engineers ask at 02:00: which number, which group, which
mailbox — and in what order. Combines:
  - link contacts (who), with roles and a primary
  - contact channels (how), several per contact = the combination
  - the escalation chain, with the reach methods attached to each step
  - availability, so nobody chases a contact who is off shift
"""
from __future__ import annotations
from sqlalchemy.orm import Session
from ..models import (Contact, ContactChannel, LinkContact, Link, EscalationRule,
                      REACH_CHANNELS, REACH_ROLE_LABELS)


def channels_for(db: Session, contact_id: int) -> list[ContactChannel]:
    rows = db.query(ContactChannel).filter(ContactChannel.contact_id == contact_id)\
        .order_by(ContactChannel.is_primary.desc(), ContactChannel.id).all()
    return rows


def channels_line(db: Session, contact: Contact) -> str:
    """'WhatsApp +2 · Email 1 · WhatsApp group 1' — human summary."""
    rows = channels_for(db, contact.id)
    if not rows:
        # fall back to the flat contact fields so nothing looks unreachable
        bits = []
        if contact.whatsapp_number:
            bits.append("WhatsApp 1")
        if contact.email:
            bits.append("Email 1")
        if contact.phone:
            bits.append("Phone 1")
        return " + ".join(bits) if bits else "NO CHANNEL RECORDED"
    counts: dict[str, int] = {}
    for r in rows:
        label = REACH_CHANNELS.get(r.channel, r.channel)
        counts[label] = counts.get(label, 0) + 1
    return " + ".join(f"{k}{'' if v == 1 else f' ({v})'}" for k, v in counts.items())


def contact_card(db: Session, contact: Contact, role: str = "") -> dict:
    chans = channels_for(db, contact.id)
    return {
        "id": contact.id,
        "name": contact.name,
        "role": role or REACH_ROLE_LABELS.get(role, role) or "Contact",
        "role_label": REACH_ROLE_LABELS.get(role, role or "Contact"),
        "team": contact.team,
        "availability": contact.availability_hours,
        "summary": channels_line(db, contact),
        "combo_note": "",
        "channels": [{"channel": c.channel,
                      "channel_label": REACH_CHANNELS.get(c.channel, c.channel),
                      "value": c.value, "label": c.label, "note": c.note,
                      "primary": bool(c.is_primary)} for c in chans],
    }


def reach_summary(db: Session, link: Link) -> dict:
    """Everything the MORE INFO panel shows for one link."""
    links = db.query(LinkContact).filter(LinkContact.link_id == link.id)\
        .order_by(LinkContact.is_primary.desc(), LinkContact.id).all()
    cards = []
    for lc in links:
        contact = db.get(Contact, lc.contact_id)
        if not contact:
            continue
        card = contact_card(db, contact, lc.role)
        card["combo_note"] = lc.combo_note or ""
        card["is_primary"] = bool(lc.is_primary)
        cards.append(card)

    # primary: explicit link contact, else the link's designated contact
    primary = None
    for c in cards:
        if c["is_primary"]:
            primary = c
            break
    if primary is None and link.primary_contact_id:
        pc = db.get(Contact, link.primary_contact_id)
        if pc:
            primary = contact_card(db, pc, "primary")
            cards.insert(0, primary)
    if primary is None and cards:
        primary = cards[0]

    chain = []
    rules = db.query(EscalationRule).filter(EscalationRule.link_id == link.id)\
        .order_by(EscalationRule.step_order).all()
    for r in rules:
        contact = db.get(Contact, r.contact_id)
        if not contact:
            continue
        chain.append({"step": r.step_order, "wait": r.wait_minutes,
                      "channels": r.channels,
                      "contact": contact_card(db, contact, "escalation")})

    kinds = sorted({c["channel"] for card in cards for c in card["channels"]})
    return {
        "primary": primary,
        "contacts": cards,
        "chain": chain,
        "kinds": kinds,
        "headline": _headline(primary, cards),
        "any_reach": bool(cards or chain),
    }


def _headline(primary: dict | None, cards: list[dict]) -> str:
    if not primary and not cards:
        return "NO CONTACT ON FILE — add one before the next outage"
    p = primary or cards[0]
    extra = f" (+{len(cards) - 1} more)" if len(cards) > 1 else ""
    return f"{p['name']}{extra} — {p['summary']}"


def compact_reach(db: Session, link: Link) -> str:
    """One line for the case page and the dashboard."""
    if not link:
        return ""
    s = reach_summary(db, link)
    if not s["any_reach"]:
        return "NO CONTACT ON FILE"
    return s["headline"]