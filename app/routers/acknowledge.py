"""One-tap acknowledgement (FR-29): stops further escalation.

GET /ack/{token}   — show a confirmation page (no state change).
POST /ack/{token}  — perform the acknowledgement.

Token expiry is enforced; expired tokens cannot be acknowledged.
"""
import os
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Notification, Case
from ..services.escalation import acknowledge
from ..config import settings
from ..utils_time import utcnow

router = APIRouter()

ACK_TOKEN_TTL_HOURS = int(os.environ.get("ACK_TOKEN_TTL_HOURS", "24") or "24")

@router.get("/ack/{token}", response_class=HTMLResponse)
def ack_confirm(token: str, request: Request, db: Session = Depends(get_db)):
    n = db.query(Notification).filter(Notification.ack_token == token).first()
    if not n:
        return HTMLResponse(
            "<h2>Unknown acknowledgement link.</h2>"
            "<p>This token does not match any notification.</p>",
            status_code=404,
        )
    case = db.get(Case, n.case_id)
    if not case:
        return HTMLResponse("<h2>Case not found.</h2>", status_code=404)
    if case.acknowledged_at:
        return HTMLResponse(
            f"<h2>Already acknowledged.</h2>"
            f"<p>NOC case {case.id} was acknowledged by {case.acknowledged_by}.</p>"
        )
    if n.ack_token_expires_at and n.ack_token_expires_at < utcnow():
        return HTMLResponse(
            "<h2>Link expired.</h2>"
            "<p>This acknowledgement link has expired. "
            "Request a fresh escalation notification.</p>",
            status_code=410,
        )
    return HTMLResponse(
        f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>Acknowledge case {case.id}</title>"
        f"<link rel='stylesheet' href='/static/style.css'></head>"
        f"<body><div class='login-wrap'><div class='login-card' style='text-align:center'>"
        f"<h2>Acknowledge case {case.id}</h2>"
        f"<p class='muted'>Link: {{ case._link_name if case._link_name else case.device }} · "
        f"Severity: {{ case.severity }}</p>"
        f"<form method='post'>"
        f"<button type='submit' class='btn login-btn'>Confirm acknowledgement</button>"
        f"</form>"
        f"<p class='muted' style='margin-top:12px'><a href='/login'>Log in to ELNOC</a> · "
        f"<a href='/'>← back to overview</a></p>"
        f"</div></div></body></html>"
    )

@router.post("/ack/{token}", response_class=HTMLResponse)
def ack_do(token: str, db: Session = Depends(get_db)):
    n = db.query(Notification).filter(Notification.ack_token == token).first()
    if not n:
        return HTMLResponse(
            "<h2>Unknown acknowledgement link.</h2>"
            "<p>This token does not match any notification.</p>",
            status_code=404,
        )
    case = db.get(Case, n.case_id)
    if not case:
        return HTMLResponse("<h2>Case not found.</h2>", status_code=404)
    if case.acknowledged_at:
        return HTMLResponse(
            f"<h2>Already acknowledged.</h2>"
            f"<p>NOC case {case.id} was acknowledged by {case.acknowledged_by}.</p>"
        )
    if n.ack_token_expires_at and n.ack_token_expires_at < utcnow():
        return HTMLResponse(
            "<h2>Link expired.</h2>"
            "<p>This acknowledgement link has expired. "
            "Request a fresh escalation notification.</p>",
            status_code=410,
        )
    acknowledge(db, case, by=f"contact#{n.contact_id}")
    return HTMLResponse(
        f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>Acknowledged</title>"
        f"<link rel='stylesheet' href='/static/style.css'></head>"
        f"<body><div class='login-wrap'><div class='login-card' style='text-align:center'>"
        f"<h2>Thank you.</h2>"
        f"<p>NOC case {case.id} acknowledged. No further escalation will be sent.</p>"
        f"<p class='muted'><a href='/login'>Log in to ELNOC</a> · "
        f"<a href='/'>← back to overview</a></p>"
        f"</div></div></body></html>"
    )
