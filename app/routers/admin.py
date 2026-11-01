"""Admin (registry, contacts, rules, users, maintenance, devices) + exports + reports."""
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path
import csv, io
import re
from ..database import get_db
from ..models import Customer, Link, Contact, EscalationRule, AppUser, MaintenanceWindow, SiteDevice, Case
from ..security import get_current_user, require_role, hash_password, audit
from ..utils_time import utcnow
from ..services.reports import weekly_report

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

USERNAME_RX = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")

@router.get("/admin", response_class=HTMLResponse)
def admin_home(request: Request, user=Depends(require_role("admin", "senior", "manager")),
               db: Session = Depends(get_db)):
    return templates.TemplateResponse(request, "admin.html", { "user": user,
         "customers": db.query(Customer).all(), "links": db.query(Link).all(),
         "contacts": db.query(Contact).all(), "rules": db.query(EscalationRule).all(),
         "users": db.query(AppUser).all(),
         "windows": db.query(MaintenanceWindow).all(),
         "devices": db.query(SiteDevice).all()})

@router.post("/admin/contacts")
def add_contact(name: str = Form(""), team: str = Form(""), phone: str = Form(""),
                email: str = Form(""), whatsapp_number: str = Form(""),
                role: str = Form(""), user=Depends(require_role("admin")),
                db: Session = Depends(get_db)):
    db.add(Contact(name=name.strip(), team=team.strip(), phone=phone.strip(),
                   email=email.strip(), whatsapp_number=(whatsapp_number or phone).strip(),
                   role=role.strip()))
    audit(db, "contact", name, user.username, "created")
    db.commit()
    return RedirectResponse(url="/admin", status_code=303)

@router.post("/admin/links")
def add_link(name: str = Form(""), customer_id: int = Form(0), circuit_id: str = Form(""),
             a_end: str = Form(""), b_end: str = Form(""), tier: str = Form("access"),
             responsible_team: str = Form("NOC"), primary_contact_id: str = Form(""),
             user=Depends(require_role("admin")), db: Session = Depends(get_db)):
    db.add(Link(name=name.strip(), customer_id=customer_id or None, circuit_id=circuit_id,
                a_end=a_end, b_end=b_end, tier=tier, responsible_team=responsible_team,
                primary_contact_id=int(primary_contact_id) if primary_contact_id else None))
    db.commit()
    return RedirectResponse(url="/admin", status_code=303)

@router.post("/admin/rules")
def add_rule(link_id: str = Form(""), customer_id: str = Form(""),
             contact_id: int = Form(0), wait_minutes: int = Form(15),
             step_order: int = Form(1), user=Depends(require_role("admin")),
             db: Session = Depends(get_db)):
    db.add(EscalationRule(link_id=int(link_id) if link_id else None,
                          customer_id=int(customer_id) if customer_id else None,
                          contact_id=contact_id, wait_minutes=wait_minutes,
                          step_order=step_order))
    db.commit()
    return RedirectResponse(url="/admin", status_code=303)

@router.post("/admin/maintenance")
def add_window(target_type: str = Form("device"), target: str = Form(""),
               start: str = Form(""), end: str = Form(""), reason: str = Form(""),
               user=Depends(require_role("admin", "senior")),
               db: Session = Depends(get_db)):
    from datetime import datetime
    db.add(MaintenanceWindow(target_type=target_type, target=target.strip(),
                             start=datetime.fromisoformat(start),
                             end=datetime.fromisoformat(end),
                             reason=reason, created_by=user.username))
    db.commit()
    return RedirectResponse(url="/admin", status_code=303)

@router.post("/admin/users")
def add_user(username: str = Form(""), name: str = Form(""), role: str = Form("engineer"),
             password: str = Form(""), user=Depends(require_role("admin")),
             db: Session = Depends(get_db)):
    username = username.strip()
    if not username:
        return RedirectResponse(url="/admin?error=username_required", status_code=303)
    if not USERNAME_RX.match(username):
        return RedirectResponse(url="/admin?error=invalid_username", status_code=303)
    if not password or len(password) < 8:
        return RedirectResponse(url="/admin?error=password_too_short", status_code=303)
    if role not in ("engineer", "senior", "manager", "admin"):
        return RedirectResponse(url="/admin?error=invalid_role", status_code=303)
    h, s = hash_password(password)
    db.add(AppUser(username=username, name=name.strip() or username,
                   role=role, active=True, password_hash=h, password_salt=s))
    db.commit()
    return RedirectResponse(url="/admin", status_code=303)

@router.get("/export/cases.csv")
def export_cases(user=Depends(get_current_user), db: Session = Depends(get_db)):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "opened_at_utc", "engineer", "customer_id", "link_id", "device",
                "severity", "status", "link_state", "waiting_on", "symptom",
                "root_cause_category", "fix", "time_to_resolve_min", "phoenix_ticket_no"])
    for c in db.query(Case).order_by(Case.id).all():
        w.writerow([c.id, c.opened_at, c.engineer, c.customer_id, c.link_id, c.device,
                    c.severity, c.status, c.link_state, c.waiting_on,
                    (c.symptom or "")[:300], c.root_cause_category,
                    (c.fix or "")[:300], c.time_to_resolve_min, c.phoenix_ticket_no])
    return Response(content=buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=elnoc-cases.csv"})

@router.get("/report/weekly", response_class=HTMLResponse)
def weekly(request: Request, user=Depends(get_current_user), db: Session = Depends(get_db)):
    rep = weekly_report(db)
    return templates.TemplateResponse(request, "weekly.html", { "user": user, "rep": rep})

@router.get("/report/weekly.csv")
def weekly_csv(user=Depends(get_current_user), db: Session = Depends(get_db)):
    rep = weekly_report(db)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["section", "key", "value"])
    for r in rep["repeats"]:
        w.writerow(["repeats", r["link"], r["count"]])
    for x in rep["waiting"]:
        w.writerow(["waiting", f"case-{x['id']} {x['link']}", f"{x['waiting_on']} {x['age_min']}m"])
    w.writerow(["mttr_min", "", rep["mttr_min"]])
    w.writerow(["complete_card", "", rep["complete_card"]])
    for q in rep.get("questioned", []):
        w.writerow(["questioned", f"case-{q['id']} {q['link']}", q["flag"]])
    for lv, n in rep.get("by_level", {}).items():
        w.writerow(["by_level", lv, n])
    return Response(content=buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=weekly-report.csv"})
