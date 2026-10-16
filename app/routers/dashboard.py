"""Dashboard (FR-25): open, waiting-with-age (red when stale), this shift, failed notifs."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path
from datetime import timedelta
from ..database import get_db
from ..models import Case, Customer, Link, Notification
from ..security import get_current_user
from ..services.escalation import is_stale_wait, is_mttr_breach
from ..services.update_watch import watch_updates, flag_text
from ..utils_time import utcnow, age_minutes, to_lagos, ensure_utc

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

def _shift_start():
    now_lagos = to_lagos(utcnow())
    # day shift 07:00, night 19:00
    start = now_lagos.replace(hour=7 if now_lagos.hour >= 7 and now_lagos.hour < 19 else 19,
                              minute=0, second=0, microsecond=0)
    if now_lagos.hour < 7:
        start = start - timedelta(days=1)
        start = start.replace(hour=19)
    return start.astimezone(utcnow().tzinfo)

@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, user=Depends(get_current_user), db: Session = Depends(get_db)):
    cases = db.query(Case).order_by(Case.opened_at.desc()).limit(300).all()
    links = {l.id: l for l in db.query(Link).all()}
    custs = {c.id: c for c in db.query(Customer).all()}
    for c in cases:
        l = links.get(c.link_id or 0)
        cu = custs.get(c.customer_id or 0)
        c._link_name = l.name if l else c.device
        c._customer_name = cu.name if cu else ""
        c._age = age_minutes(c.opened_at)
        c._stale = is_stale_wait(c)
        c._breach = is_mttr_breach(c)
        c._upd = None  # filled lazily below for visible lists only
    open_cases = [c for c in cases if c.status in ("open", "escalated")]
    waiting = [c for c in cases if c.status == "waiting_other_team"]
    shift_cases = [c for c in cases if c.opened_at and ensure_utc(c.opened_at) >= _shift_start()]
    from ..models import CaseEvent
    for c in open_cases + waiting:
        evs = db.query(CaseEvent).filter(CaseEvent.case_id == c.id).all()
        c._upd = watch_updates(c.symptom or "", c.opened_at, evs)
        c._upd_flag = flag_text(c._upd)
    failed = db.query(Notification).filter(Notification.status == "failed")\
        .order_by(Notification.id.desc()).limit(20).all()
    return templates.TemplateResponse(request, "dashboard.html", { "user": user, "open_cases": open_cases, "waiting": waiting,
         "shift_cases": shift_cases, "failed": failed, "total": len(cases)})

@router.get("/api/deck-stats")
def deck_stats(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Live numbers for the command deck (polled every 45s, auth required)."""
    from sqlalchemy import func
    open_n = db.query(func.count()).select_from(Case)\
        .filter(Case.status.in_(["open", "escalated"])).scalar() or 0
    waiting_n = db.query(func.count()).select_from(Case)\
        .filter(Case.status == "waiting_other_team").scalar() or 0
    shift_n = db.query(func.count()).select_from(Case)\
        .filter(Case.opened_at >= _shift_start().replace(tzinfo=None)).scalar() or 0
    total_n = db.query(func.count()).select_from(Case).scalar() or 0
    from fastapi.responses import JSONResponse
    return JSONResponse({"open": open_n, "waiting": waiting_n,
                         "shift": shift_n, "total": total_n})
