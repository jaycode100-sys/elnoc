"""Playbooks (FR-50..FR-52): numbered steps, owner, stale badge after 90 days."""
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path
from datetime import timedelta
from ..database import get_db
from ..models import Playbook
from ..security import get_current_user, require_role
from ..utils_time import utcnow

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

def is_stale(pb: Playbook) -> bool:
    if not pb.last_confirmed_at:
        return True
    try:
        from ..utils_time import ensure_utc
        return (utcnow() - ensure_utc(pb.last_confirmed_at)).days > 90
    except Exception:
        return True

@router.get("/playbooks", response_class=HTMLResponse)
def list_pb(request: Request, user=Depends(get_current_user), db: Session = Depends(get_db)):
    pbs = db.query(Playbook).order_by(Playbook.id.desc()).all()
    for p in pbs:
        p._stale = is_stale(p)
    return templates.TemplateResponse(request, "playbooks.html", { "user": user, "pbs": pbs})

@router.post("/playbooks")
def create_pb(title: str = Form(""), trigger_category: str = Form(""),
              steps: str = Form(""), owner: str = Form(""),
              who_to_call: str = Form(""), when_to_escalate: str = Form(""),
              user=Depends(require_role("senior", "admin")),
              db: Session = Depends(get_db)):
    db.add(Playbook(title=title.strip(), trigger_category=trigger_category.strip(),
                    steps=steps, owner=owner or user.username,
                    who_to_call=who_to_call, when_to_escalate=when_to_escalate,
                    last_confirmed_at=utcnow()))
    db.commit()
    return RedirectResponse(url="/playbooks", status_code=303)

@router.post("/playbooks/{pid}/confirm")
def confirm_pb(pid: int, user=Depends(require_role("senior", "admin")),
               db: Session = Depends(get_db)):
    pb = db.get(Playbook, pid)
    pb.last_confirmed_at = utcnow()
    db.commit()
    return RedirectResponse(url="/playbooks", status_code=303)
