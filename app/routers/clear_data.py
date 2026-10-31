"""Database clear / reset utility.

POST /api/admin/clear-data  — wipes cases, customers, links, contacts,
escalation rules, power reports, shift notes, assistant threads/messages,
agent logs, notifications, events, attachments, handovers.

The permanent superadmin user is preserved (stored outside the DB in
%LOCALAPPDATA%\ELNOC\superadmin.json and re-seeded on login).

Only callable by admin. Irreversible.
"""
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from ..database import get_db
from ..security import require_role
from ..services.superadmin import superadmin_username

router = APIRouter()

# Order matters: children before parents (FK constraints)
_CLEAR_ORDER = [
    "assistant_message",
    "assistant_thread",
    "agent_log",
    "notification",
    "case_event",
    "case_link",
    "attachment",
    "case_tbl",
    "power_report",
    "shift_note",
    "handover_import",
    "handover",
    "escalation_rule",
    "link_contact",
    "contact_channel",
    "site_device",
    "link",
    "contact",
    "customer",
    "optical_reading",
    "event",
    "audit_log",
]


@router.post("/api/admin/clear-data")
def api_clear_data(user=Depends(require_role("admin")),
                   db: Session = Depends(get_db)):
    from sqlalchemy import text
    counts = {}
    su = superadmin_username()
    with db.begin_nested():
        for table in _CLEAR_ORDER:
            try:
                if table == "app_user":
                    # Preserve the permanent superadmin user record
                    result = db.execute(text(f"DELETE FROM {table} WHERE username != :su"),
                                        {"su": su})
                else:
                    result = db.execute(text(f"DELETE FROM {table}"))
                counts[table] = result.rowcount
            except Exception:
                counts[table] = 0
    db.commit()
    return JSONResponse({"cleared": counts, "message": "All data cleared. Superadmin preserved.",
                         "superadmin": su})
