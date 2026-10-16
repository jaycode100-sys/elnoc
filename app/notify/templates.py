"""Fixed notification template sec 10.3 (FR-33). Times always carry WAT (NFR-12)."""
from __future__ import annotations
from ..utils_time import fmt_wat

STATUS_LABEL = {
    "open": "new", "escalated": "escalated",
    "waiting_other_team": "waiting", "resolved": "resolved",
}

def render_notification(case, event_summary: str, affected: str, status: str | None = None) -> str:
    sev = (case.severity or "major").upper()
    st = STATUS_LABEL.get((status or case.status), case.status)
    base = getattr(__import__("app.config", fromlist=["settings"]), "settings").BASE_URL
    return (
        f"NOC case {case.id} | {sev}\n"
        f"Event:     {event_summary or case.symptom or ''}\n"
        f"Affected:  {affected}\n"
        f"Detected:  {fmt_wat(case.opened_at)}\n"
        f"Status:    {st}\n"
        f"Case:      {base}/cases/{case.id}\n"
        f"Acknowledge: {base}/ack/{{token}}\n"
    )

def render_short(case, event_summary: str, affected: str) -> str:
    """SMS/WhatsApp short form: first four lines + link (sec 10.3)."""
    full = render_notification(case, event_summary, affected)
    lines = full.splitlines()
    return "\n".join(lines[:4] + [lines[5]])
