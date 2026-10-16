"""Copy for Phoenix (FR-17) — one-step plain-text paste. Phoenix stays official record."""
from __future__ import annotations
from ..utils_time import fmt_wat

def phoenix_text(case, customer_name: str = "", link_name: str = "") -> str:
    lines = [
        f"Phoenix ticket ref: {case.phoenix_ticket_no or '(new — paste ELNOC id after creation)'}",
        f"Customer: {customer_name}",
        f"Link: {link_name} | Circuit: {getattr(case, 'circuit_id', '') or ''}",
        f"Device: {case.device or ''}",
        f"Detected: {fmt_wat(case.opened_at)} | Severity: {case.severity}",
        f"Symptom: {case.symptom or ''}",
        f"Checks done: {case.checks_done or ''}",
        f"Root cause: {case.root_cause_category or ''} {case.root_cause_detail or ''}".strip(),
        f"Fix: {case.fix or ''}",
        f"First check next time: {case.first_thing_to_check_next_time or ''}",
        f"ELNOC case #{case.id} | Status: {case.status} | Link state: {case.link_state}",
    ]
    return "\n".join(lines)
