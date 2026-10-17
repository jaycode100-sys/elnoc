"""Case lifecycle (FR-20..FR-25, FR-31/32): timeline, close-out, similar, evidence."""
from fastapi import APIRouter, Depends, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path
import hashlib
from ..database import get_db
from ..models import Case, CaseEvent, Customer, Link, CaseLink, Attachment, ROOT_CAUSE_CATEGORIES, ESCALATION_LEVELS, EVIDENCE_KINDS
from ..security import get_current_user, find_secret, audit
from ..services.similar import similar_cases, sync_fts
from ..services.escalation import is_stale_wait, is_mttr_breach
from ..services.phoenix_fmt import phoenix_text
from ..services.update_watch import watch_updates, flag_text
from ..utils_time import utcnow, age_minutes, ensure_utc

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))
EVIDENCE_DIR = Path("evidence"); EVIDENCE_DIR.mkdir(exist_ok=True)

def _update_watch(db, case):
    evs = db.query(CaseEvent).filter(CaseEvent.case_id == case.id).all()
    w = watch_updates(case.symptom or "", case.opened_at, evs)
    w["flag"] = flag_text(w)
    return w

def _names(db, case):
    cust = db.get(Customer, case.customer_id) if case.customer_id else None
    link = db.get(Link, case.link_id) if case.link_id else None
    return (cust.name if cust else "", link.name if link else "")

@router.post("/cases/{case_id}/chase")
def stamp_chase(case_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Record a contact attempt (B3 item 20: time of last contact attempt)."""
    case = db.get(Case, case_id)
    case.last_contact_attempt_at = utcnow()
    db.add(CaseEvent(case_id=case_id, at=utcnow(), engineer=user.username,
                     kind="escalation",
                     text=f"Chased {case.waiting_on or 'party'} — contact attempt logged."))
    db.commit()
    return RedirectResponse(url=f"/cases/{case_id}", status_code=303)

@router.get("/cases", response_class=HTMLResponse)
def case_list(request: Request, status: str = "", user=Depends(get_current_user),
              db: Session = Depends(get_db)):
    q = db.query(Case).order_by(Case.opened_at.desc()).limit(200)
    cases = q.all()
    if status:
        cases = [c for c in cases if c.status == status]
    for c in cases:
        cn, ln = _names(db, c)
        c._customer_name, c._link_name = cn, ln
        c._stale = is_stale_wait(c)
        c._breach = is_mttr_breach(c)
        c._age = age_minutes(c.opened_at)
    return templates.TemplateResponse(request, "cases.html", { "user": user, "cases": cases, "status": status})

@router.get("/cases/{case_id}", response_class=HTMLResponse)
def case_page(request: Request, case_id: int, user=Depends(get_current_user),
              db: Session = Depends(get_db)):
    case = db.get(Case, case_id)
    if not case:
        return HTMLResponse("not found", status_code=404)
    cn, ln = _names(db, case)
    events = db.query(CaseEvent).filter(CaseEvent.case_id == case.id).order_by(CaseEvent.at).all()
    sims = similar_cases(db, case)
    for s in sims:
        a, b = _names(db, s)
        s._customer_name, s._link_name = a, b
    atts = db.query(Attachment).filter(Attachment.case_id == case.id).all()
    affected = [db.get(Link, cl.link_id).name for cl in
                db.query(CaseLink).filter(CaseLink.case_id == case.id).all()
                if db.get(Link, cl.link_id)]
    # playbook suggestion (FR-52)
    from ..models import Playbook
    sug = db.query(Playbook).filter(
        Playbook.trigger_category == case.root_cause_category).limit(3).all() \
        if case.root_cause_category else []
    # promotion prompt (FR-50)
    promo = None
    if case.root_cause_category:
        n = db.query(Case).filter(Case.root_cause_category == case.root_cause_category,
                                  Case.link_id == case.link_id).count()
        if n >= 3 and user.role in ("senior", "admin"):
            promo = f"{n} cases share category '{case.root_cause_category}' on this link — consider promoting to a playbook."
    evs = db.query(CaseEvent).filter(CaseEvent.case_id == case.id).all()
    from ..routers.evidence import outstanding_challenge, thread_rows
    from ..services.link_state import recommend, challenge_card, challenge_text
    rec = recommend(db, case)
    return templates.TemplateResponse(request, "case.html", { "user": user, "case": case, "customer_name": cn, "link_name": ln,
         "events": events, "sims": sims, "atts": atts, "affected": affected,
         "categories": ROOT_CAUSE_CATEGORIES, "stale": is_stale_wait(case),
         "levels": ESCALATION_LEVELS, "suggested": sug, "promo": promo,
         "upd": _update_watch(db, case),
         "state_rec": challenge_card(rec), "state_why": rec["why"],
         "state_challenge": challenge_text(rec),
         "evidence": thread_rows(db, case.id),
         "ev_kinds": EVIDENCE_KINDS,
         "resolution_challenge": outstanding_challenge(db, case.id)})

@router.post("/cases/{case_id}/notes")
def add_note(case_id: int, text: str = Form(""), kind: str = Form("note"),
             user=Depends(get_current_user), db: Session = Depends(get_db)):
    case = db.get(Case, case_id)
    hit = find_secret(text)
    if hit:
        return HTMLResponse(f"Blocked: possible secret ({hit})", status_code=400)
    db.add(CaseEvent(case_id=case.id, at=utcnow(), engineer=user.username,
                     kind=kind or "note", text=text[:4000]))
    audit(db, "case", str(case.id), user.username, f"note added ({kind})")
    db.commit()
    cn, ln = _names(db, case)
    sync_fts(db, case, cn, ln)
    return RedirectResponse(url=f"/cases/{case.id}", status_code=303)

@router.post("/cases/{case_id}/status")
def change_status(case_id: int, status: str = Form("open"), link_state: str = Form(""),
                  waiting_on: str = Form(""), escalation_level: str = Form(""),
                  phoenix_ticket_no: str = None, user=Depends(get_current_user),
                  db: Session = Depends(get_db)):
    case = db.get(Case, case_id)
    old = case.status
    case.status = status
    if link_state:
        case.link_state = link_state
        # stamp restoration the moment a link is declared up (summary block)
        if link_state == "up" and not case.restored_at:
            case.restored_at = utcnow()
    if waiting_on is not None:
        case.waiting_on = waiting_on.strip().upper()
    if escalation_level in ("", "L1", "L2", "L3", "Vendor"):
        if escalation_level:
            case.escalation_level = escalation_level
    # Phoenix ticket trail: app-only, never in the handover text.
    if phoenix_ticket_no is not None:
        new_ticket = phoenix_ticket_no.strip()
        if new_ticket and new_ticket != (case.phoenix_ticket_no or "").strip():
            case.phoenix_ticket_no = new_ticket
            if not case.phoenix_ticket_opened_at:
                case.phoenix_ticket_opened_at = utcnow()
    if status == "waiting_other_team":
        case.last_escalation_at = utcnow()
    db.add(CaseEvent(case_id=case.id, at=utcnow(), engineer=user.username, kind="status",
                     text=f"Status {old} -> {status}; link_state={case.link_state}; waiting_on={case.waiting_on}; level={case.escalation_level}"
                          + (f"; Phoenix ticket {case.phoenix_ticket_no}" if case.phoenix_ticket_no else "")))
    audit(db, "case", str(case.id), user.username, f"status {old}->{status}")
    db.commit()
    return RedirectResponse(url=f"/cases/{case.id}", status_code=303)

@router.post("/cases/{case_id}/close")
def close_case(case_id: int, root_cause_category: str = Form(""),
               root_cause_detail: str = Form(""), fix: str = Form(""),
               first_thing_to_check_next_time: str = Form(""),
               user=Depends(get_current_user), db: Session = Depends(get_db)):
    case = db.get(Case, case_id)
    # FR-22 close-out rules
    if not root_cause_category or not fix.strip() or not first_thing_to_check_next_time.strip():
        return HTMLResponse("Closing requires root-cause category, fix and first-thing-to-check (FR-22).",
                            status_code=400)
    for blob in (root_cause_detail, fix, first_thing_to_check_next_time):
        hit = find_secret(blob)
        if hit:
            return HTMLResponse(f"Blocked: possible secret ({hit})", status_code=400)
    case.root_cause_category = root_cause_category
    case.root_cause_detail = root_cause_detail
    case.fix = fix
    case.first_thing_to_check_next_time = first_thing_to_check_next_time
    case.status = "resolved"
    case.link_state = "up"
    case.closed_at = utcnow()
    try:
        case.time_to_resolve_min = int((ensure_utc(case.closed_at) - ensure_utc(case.opened_at)).total_seconds() // 60)
    except Exception:
        case.time_to_resolve_min = 0
    db.add(CaseEvent(case_id=case.id, at=utcnow(), engineer=user.username, kind="status",
                     text=f"Resolved: {root_cause_category} — {fix[:200]}"))
    audit(db, "case", str(case.id), user.username, "closed")
    db.commit()
    cn, ln = _names(db, case)
    sync_fts(db, case, cn, ln)
    return RedirectResponse(url=f"/cases/{case.id}", status_code=303)

@router.post("/cases/{case_id}/watcher")
def add_watcher(case_id: int, contact_id: int = Form(0), user=Depends(get_current_user),
                db: Session = Depends(get_db)):
    from ..models import CaseWatcher, Contact
    case = db.get(Case, case_id)
    contact = db.get(Contact, contact_id)
    if not contact:
        return HTMLResponse("contact not found", status_code=404)
    # FR-27: one optional watcher per case (unique constraint guards noise)
    existing = db.query(CaseWatcher).filter(CaseWatcher.case_id == case.id).all()
    if len(existing) >= 1 and not any(w.contact_id == contact.id for w in existing):
        return HTMLResponse("Only one optional watcher per case (FR-27). Remove one first.",
                            status_code=400)
    db.add(CaseWatcher(case_id=case.id, contact_id=contact.id,
                       added_by=user.username, added_at=utcnow()))
    try:
        db.commit()
    except Exception:
        db.rollback()
    db.add(CaseEvent(case_id=case.id, at=utcnow(), engineer=user.username, kind="escalation",
                     text=f"Watcher added: {contact.name} by {user.username}"))
    db.commit()
    return RedirectResponse(url=f"/cases/{case.id}", status_code=303)

@router.post("/cases/{case_id}/attachments")
async def upload_evidence(case_id: int, request: Request, file: UploadFile = File(None),
                          note: str = Form(""), user=Depends(get_current_user),
                          db: Session = Depends(get_db)):
    case = db.get(Case, case_id)
    if file is None:
        return HTMLResponse("no file", status_code=400)
    data = await file.read()
    if len(data) > 15 * 1024 * 1024:
        return HTMLResponse("file too large (15MB max)", status_code=400)
    digest = hashlib.sha256(data).hexdigest()
    safe = "".join(c for c in (file.filename or "evidence") if c.isalnum() or c in "._-")[:120]
    dest = EVIDENCE_DIR / f"case{case.id}-{digest[:12]}-{safe}"
    dest.write_bytes(data)
    db.add(Attachment(case_id=case.id, filename=file.filename or safe, stored_path=str(dest),
                      sha256=digest, uploaded_by=user.username, uploaded_at=utcnow(),
                      note=note[:500]))
    db.add(CaseEvent(case_id=case.id, at=utcnow(), engineer=user.username, kind="note",
                     text=f"Evidence attached: {file.filename} (sha256 {digest[:12]})"))
    db.commit()
    return RedirectResponse(url=f"/cases/{case.id}", status_code=303)

@router.get("/cases/{case_id}/phoenix.txt", response_class=PlainTextResponse)
def copy_for_phoenix(case_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    case = db.get(Case, case_id)
    cn, ln = _names(db, case)
    link = db.get(Link, case.link_id) if case.link_id else None
    case.circuit_id = link.circuit_id if link else ""
    return phoenix_text(case, cn, ln)
