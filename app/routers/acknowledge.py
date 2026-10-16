"""One-tap acknowledgement (FR-29): stops further escalation."""
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Notification, Case
from ..services.escalation import acknowledge

router = APIRouter()

@router.get("/ack/{token}", response_class=HTMLResponse)
def ack(token: str, db: Session = Depends(get_db)):
    n = db.query(Notification).filter(Notification.ack_token == token).first()
    if not n:
        return HTMLResponse("<h2>Unknown or expired acknowledgement link.</h2>", status_code=404)
    case = db.get(Case, n.case_id)
    if not case:
        return HTMLResponse("<h2>Case not found.</h2>", status_code=404)
    if case.acknowledged_at:
        return HTMLResponse(f"<h2>Case {case.id} already acknowledged by {case.acknowledged_by}.</h2>")
    acknowledge(db, case, by=f"contact#{n.contact_id}")
    return HTMLResponse(
        f"<h2>Thank you.</h2><p>NOC case {case.id} acknowledged. No further escalation will be sent.</p>")
