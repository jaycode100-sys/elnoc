"""Quick Log (FR-11..FR-18): one search box, auto-fill, quick-create, alias learning."""
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path
from ..database import get_db
from ..models import Link, Customer, Case, CaseEvent
from ..security import get_current_user, find_secret, audit
from ..services.search import search_links, learn_alias
from ..services.similar import sync_fts
from ..services.phoenix_fmt import phoenix_text
from ..utils_time import utcnow, ensure_utc, fmt_wat
from datetime import datetime, timezone

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

@router.get("/quicklog", response_class=HTMLResponse)
def quicklog_page(request: Request, q: str = "", device: str = "",
                  user=Depends(get_current_user), db: Session = Depends(get_db)):
    results = search_links(db, q) if q else []
    return templates.TemplateResponse(request, "quicklog.html", { "user": user, "q": q, "device": device, "results": results})

@router.get("/api/search")
def api_search(q: str = "", db: Session = Depends(get_db), user=Depends(get_current_user)):
    return JSONResponse(search_links(db, q))

@router.get("/api/link-info/{link_id}")
def link_info(link_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    link = db.get(Link, link_id)
    if not link:
        return JSONResponse({"error": "not found"}, status_code=404)
    cust = db.get(Customer, link.customer_id) if link.customer_id else None
    last3 = db.query(Case).filter(Case.link_id == link.id).order_by(Case.opened_at.desc()).limit(3).all()
    from ..models import EscalationRule, Contact
    rules = db.query(EscalationRule).filter(EscalationRule.link_id == link.id)\
        .order_by(EscalationRule.step_order).all()
    steps = []
    for r in rules:
        c = db.get(Contact, r.contact_id)
        steps.append({"order": r.step_order, "contact": c.name if c else "",
                      "wait": r.wait_minutes, "channels": r.channels})
    return JSONResponse({
        "link_id": link.id, "link_name": link.name, "circuit_id": link.circuit_id,
        "customer": cust.name if cust else "", "customer_id": cust.id if cust else None,
        "a_end": link.a_end, "b_end": link.b_end,
        "responsible_team": link.responsible_team, "tier": link.tier,
        "steps": steps,
        "last3": [{"id": c.id, "symptom": (c.symptom or "")[:160], "status": c.status,
                   "fix": (c.fix or "")[:160]} for c in last3],
    })

@router.post("/api/quicklog")
def api_quicklog(request: Request, payload: dict, db: Session = Depends(get_db),
                 user=Depends(get_current_user)):
    symptom = (payload.get("symptom") or "").strip()
    if not symptom:
        return JSONResponse({"error": "symptom required"}, status_code=400)
    hit = find_secret(symptom + " " + (payload.get("device") or ""))
    if hit:
        return JSONResponse({"error": f"Blocked: possible secret ({hit}). Remove credentials and retry."},
                            status_code=400)
    link_id = payload.get("link_id")
    typed = (payload.get("typed_query") or "").strip()
    link = db.get(Link, link_id) if link_id else None
    if not link:
        # FR-15 quick-create from 3 fields
        cname = (payload.get("customer_name") or "Unknown").strip() or "Unknown"
        lname = (payload.get("link_name") or "").strip()
        circ = (payload.get("circuit_id") or "").strip()
        if not lname:
            return JSONResponse({"error": "pick a link or supply link_name"}, status_code=400)
        cust = db.query(Customer).filter(Customer.name == cname).first()
        if not cust:
            cust = Customer(name=cname); db.add(cust); db.flush()
        link = Link(name=lname, customer_id=cust.id, circuit_id=circ,
                    responsible_team="NOC", aliases=typed.lower())
        db.add(link); db.flush()
    else:
        if typed:
            learn_alias(db, typed, "link", link.id)  # FR-16
    device = (payload.get("device") or "").strip()  # FR-14: from window title only
    # Pane parity: "Issue Detected" (engineer-reported, optional) vs the
    # system-managed escalation time (opened_at, always server now).
    issue_note = None
    raw_issue = (payload.get("issue_detected_at") or "").strip()
    if raw_issue:
        try:
            issue_dt = ensure_utc(datetime.fromisoformat(raw_issue.replace("Z", "+00:00")))
            issue_note = f"Issue detected (engineer-reported): {fmt_wat(issue_dt)}."
        except ValueError:
            return JSONResponse({"error": "issue_detected_at must be ISO datetime"}, status_code=400)
    lvl = (payload.get("escalation_level") or "").strip()
    if lvl not in ("L1", "L2", "L3", "Vendor"):
        lvl = ""
    case = Case(engineer=user.username, customer_id=link.customer_id, link_id=link.id,
                device=device, symptom=symptom,
                status=payload.get("status") or "open",
                severity=payload.get("severity") or "major",
                link_state=payload.get("link_state") or "down",
                escalation_level=lvl,
                opened_by="manual", opened_at=utcnow())
    db.add(case); db.flush()
    db.add(CaseEvent(case_id=case.id, at=utcnow(), engineer=user.username,
                     kind="note", text=f"Quick-logged: {symptom} [device: {device}]"))
    if issue_note:
        db.add(CaseEvent(case_id=case.id, at=utcnow(), engineer=user.username,
                         kind="note", text=issue_note))
    audit(db, "case", str(case.id), user.username, f"created via quicklog link={link.id}")
    db.commit()
    cust = db.get(Customer, link.customer_id) if link.customer_id else None
    sync_fts(db, case, cust.name if cust else "", link.name)
    case.circuit_id = link.circuit_id  # phoenix formatter reads it off the case
    return JSONResponse({"case_id": case.id, "link": link.name,
                         "phoenix_url": f"/cases/{case.id}/phoenix.txt",
                         "phoenix_text": phoenix_text(case, cust.name if cust else "", link.name),
                         "escalation_time": fmt_wat(case.opened_at),
                         "issue_detected": issue_note or ""})
