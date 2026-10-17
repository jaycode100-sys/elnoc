"""Link registry + MORE INFO: how we reach this client (FR-18 territory)."""
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path
from ..database import get_db
from ..models import (Link, Customer, Contact, LinkContact, ContactChannel,
                      REACH_CHANNELS, REACH_ROLE_LABELS, Case)
from ..security import get_current_user, require_role, audit
from ..services.contacts import reach_summary, compact_reach
from ..services.escalation import is_stale_wait
from ..utils_time import utcnow, age_minutes

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/links", response_class=HTMLResponse)
def links_index(request: Request, user=Depends(get_current_user),
                db: Session = Depends(get_db)):
    rows = db.query(Link).order_by(Link.name).all()
    for l in rows:
        l._reach = compact_reach(db, l)
    return templates.TemplateResponse(request, "links.html",
        {"user": user, "links": rows})


@router.get("/links/{link_id:int}", response_class=HTMLResponse)
def link_more_info(link_id: int, request: Request, user=Depends(get_current_user),
                   db: Session = Depends(get_db)):
    link = db.get(Link, link_id)
    if not link:
        return HTMLResponse("Link not found", status_code=404)
    cust = db.get(Customer, link.customer_id) if link.customer_id else None
    reach = reach_summary(db, link)
    cases = db.query(Case).filter(Case.link_id == link.id)\
        .order_by(Case.opened_at.desc()).limit(10).all()
    for c in cases:
        c._stale = is_stale_wait(c)
        c._age = age_minutes(c.opened_at)
    contacts = db.query(Contact).order_by(Contact.name).all()
    return templates.TemplateResponse(request, "link_info.html", {
        "user": user, "link": link, "customer": cust, "reach": reach,
        "cases": cases, "contacts": contacts,
        "reach_channels": REACH_CHANNELS, "role_labels": REACH_ROLE_LABELS,
        "reach_line": compact_reach(db, link)})


@router.post("/links/{link_id:int}/contacts")
def add_link_contact(link_id: int, contact_id: int = Form(0),
                     role: str = Form("contact"), combo_note: str = Form(""),
                     is_primary: str = Form(""), user=Depends(require_role("admin", "senior")),
                     db: Session = Depends(get_db)):
    link = db.get(Link, link_id)
    contact = db.get(Contact, contact_id)
    if not contact:
        return HTMLResponse("Contact not found", status_code=404)
    if is_primary:
        for lc in db.query(LinkContact).filter(LinkContact.link_id == link.id).all():
            lc.is_primary = False
    exists = db.query(LinkContact).filter(
        LinkContact.link_id == link.id, LinkContact.contact_id == contact.id).first()
    if exists:
        exists.role = role or exists.role
        exists.combo_note = combo_note or exists.combo_note
        exists.is_primary = bool(is_primary) or exists.is_primary
    else:
        db.add(LinkContact(link_id=link.id, contact_id=contact.id,
                           role=role or "contact", combo_note=combo_note[:300],
                           is_primary=bool(is_primary)))
    audit(db, "link", str(link.id), user.username,
          f"contact {contact.name} role={role} primary={bool(is_primary)}")
    db.commit()
    return RedirectResponse(url=f"/links/{link.id}", status_code=303)


@router.post("/links/{link_id:int}/contacts/{lc_id:int}/remove")
def remove_link_contact(link_id: int, lc_id: int, user=Depends(require_role("admin")),
                        db: Session = Depends(get_db)):
    lc = db.get(LinkContact, lc_id)
    if lc and lc.link_id == link_id:
        db.delete(lc)
        db.commit()
    return RedirectResponse(url=f"/links/{link_id}", status_code=303)


@router.post("/contacts/{contact_id:int}/channels")
def add_channel(contact_id: int, channel: str = Form("whatsapp"),
                value: str = Form(""), label: str = Form(""), note: str = Form(""),
                is_primary: str = Form(""), user=Depends(require_role("admin", "senior")),
                db: Session = Depends(get_db)):
    contact = db.get(Contact, contact_id)
    if not contact:
        return HTMLResponse("Contact not found", status_code=404)
    if channel not in REACH_CHANNELS:
        channel = "whatsapp"
    db.add(ContactChannel(contact_id=contact.id, channel=channel,
                          value=value.strip()[:300], label=label.strip()[:200],
                          note=note[:400], is_primary=bool(is_primary)))
    audit(db, "contact", str(contact.id), user.username,
          f"channel {channel} added")
    db.commit()
    return RedirectResponse(url=request.headers.get("referer", "/links"),
                            status_code=303)


@router.post("/contacts/{contact_id:int}/channels/{ch_id:int}/remove")
def remove_channel(contact_id: int, ch_id: int, user=Depends(require_role("admin")),
                   db: Session = Depends(get_db)):
    ch = db.get(ContactChannel, ch_id)
    if ch and ch.contact_id == contact_id:
        db.delete(ch)
        db.commit()
    return RedirectResponse(url=request.headers.get("referer", "/links"),
                            status_code=303)