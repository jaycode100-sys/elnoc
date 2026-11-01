"""Database clear / reset utility.

POST /api/admin/clear-data — wipes cases, customers, links, contacts,
escalation rules, power reports, shift notes, assistant threads/messages,
agent logs, notifications, events, attachments, handovers.

Requires a confirmation token (?confirm=CLEAR_ALL_DATA) to prevent accidental
invocation. The permanent superadmin user is preserved (stored outside the DB
and re-seeded on login).

Only callable by admin. Irreversible.
"""
from fastapi import APIRouter, Depends, Query
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

CLEAR_CONFIRM_TOKEN = "CLEAR_ALL_DATA"


@router.post("/api/admin/clear-data")
def api_clear_data(confirm: str = Query(None),
                   user=Depends(require_role("admin")),
                   db: Session = Depends(get_db)):
    if confirm != CLEAR_CONFIRM_TOKEN:
        return JSONResponse(
            {"error": "Confirmation required. Add ?confirm=CLEAR_ALL_DATA to the URL."},
            status_code=400,
        )
    from sqlalchemy import text
    counts = {}
    su = superadmin_username()
    errors = []
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
            except Exception as e:
                counts[table] = 0
                errors.append(f"{table}: {e}")
    db.commit()
    return JSONResponse({
        "cleared": counts,
        "errors": errors,
        "message": "All data cleared. Superadmin preserved.",
        "superadmin": su,
    })
