"""ELNOC agentic tools — actions the AI assistant can take on the user's behalf.

Each tool returns a plain dict that the agent pipeline feeds back to the model,
so the model can chain observations before giving a final answer. All tools are
read-safe by default; state-changing tools (create_case, acknowledge_case)
require explicit confirmation in the user's message before they fire.
"""
from __future__ import annotations

import re
from typing import Optional
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Case, Link, Customer, CaseEvent, Playbook, OpticalReading
from ..security import get_current_user, find_secret
from ..services.ai_assist import interpret_rsl
from ..services.search import search_links
from ..utils_time import utcnow


def _case_context(db: Session, case: Case) -> str:
    """Facts about the case, so the answer is about THIS link, not generic."""
    if not case:
        return "No case attached."
    lines = [f"CASE #{case.id}"]
    link = db.get(Link, case.link_id) if case.link_id else None
    cust = db.get(Customer, case.customer_id) if case.customer_id else None
    if link:
        lines.append(f"LINK: {link.name} (circuit {link.circuit_id or '?'}, "
                     f"{link.a_end} -> {link.b_end}, {link.medium})")
    if cust:
        lines.append(f"CUSTOMER: {cust.name}")
    lines.append(f"STATE: {case.link_state} | STATUS: {case.status} | "
                 f"SEVERITY: {case.severity} | LEVEL: {case.escalation_level}")
    if case.symptom:
        lines.append(f"SYMPTOM: {case.symptom}")
    if case.waiting_on:
        lines.append(f"WAITING ON: {case.waiting_on}")
    evs = db.query(CaseEvent).filter(CaseEvent.case_id == case.id)\
        .order_by(CaseEvent.at.desc()).limit(6).all()
    if evs:
        lines.append("RECENT UPDATES:")
        lines.extend(f"  - {e.kind}: {e.text[:200]}" for e in evs)
    if link:
        rs = db.query(OpticalReading).filter(OpticalReading.link_id == link.id)\
            .order_by(OpticalReading.occurred_at.desc()).limit(5).all()
        if rs:
            lines.append("RECENT OPTICAL READINGS: "
                         + ", ".join(f"{r.rsl_dbm} dBm" for r in rs if r.rsl_dbm is not None))
    if rs and rs[0].rsl_dbm is not None:
        v = interpret_rsl(rs[0].rsl_dbm)
        lines.append(f"ELNOC COMPUTED VERDICT (do not recalculate): "
                     f"{v['status']}, margin {v['margin_db']} dB to the "
                     f"{v['limits']['fail_dbm']} dBm fail floor. "
                     f"Likely causes: {'; '.join(v['likely_causes'])}")
    return "\n".join(lines)


# ---------------------------------------------------------------- read tools

def _names(db: Session, case: Case) -> tuple[str, str]:
    cust = db.get(Customer, case.customer_id) if case.customer_id else None
    link = db.get(Link, case.link_id) if case.link_id else None
    return (cust.name if cust else "—", link.name if link else "—")


def tool_search_playbooks(query: str, db: Session) -> dict:
    """Search ELNOC's own playbook knowledge base."""
    rows = db.query(Playbook).all()
    words = {w.lower() for w in query.split() if len(w) > 3}
    scored = sorted(rows, key=lambda p: -sum(
        1 for w in words if w in ((p.title or "") + " " + (p.trigger_category or "")).lower()))
    top = scored[:5]
    if not top:
        return {"tool": "search_playbooks", "query": query, "results": [],
                "summary": "No playbooks matched that query."}
    return {
        "tool": "search_playbooks", "query": query,
        "results": [{"id": p.id, "title": p.title or "",
                     "category": p.trigger_category or "",
                     "steps": (p.steps or "")[:220]} for p in top],
        "summary": f"Found {len(top)} playbook(s) most relevant to “{query}”.",
    }


def tool_check_link(link_name_or_id: str, db: Session) -> dict:
    """Look up a link by name or numeric id: customer, tier, circuit, escalation steps."""
    link = None
    try:
        link = db.get(Link, int(link_name_or_id))
    except ValueError:
        link = db.query(Link).filter(Link.name.ilike(f"%{link_name_or_id}%")).first()
    if not link:
        return {"tool": "check_link", "query": link_name_or_id,
                "results": {}, "summary": f"Link “{link_name_or_id}” not found."}
    from ..models import EscalationRule, Contact
    rules = db.query(EscalationRule).filter(EscalationRule.link_id == link.id)\
        .order_by(EscalationRule.step_order).all()
    steps = []
    for r in rules:
        c = db.get(Contact, r.contact_id)
        steps.append({"order": r.step_order, "contact": c.name if c else "—",
                      "wait_min": r.wait_minutes, "channels": r.channels})
    cust = db.get(Customer, link.customer_id) if link.customer_id else None
    cases = db.query(Case).filter(Case.link_id == link.id)\
        .order_by(Case.opened_at.desc()).limit(3).all()
    return {
        "tool": "check_link", "query": link_name_or_id,
        "results": {
            "name": link.name, "circuit_id": link.circuit_id or "—",
            "customer": cust.name if cust else "—", "tier": link.tier,
            "medium": link.medium, "responsible_team": link.responsible_team,
            "a_end": link.a_end, "b_end": link.b_end,
            "escalation_steps": steps,
            "recent_cases": [{"id": x.id, "symptom": (x.symptom or "")[:140],
                              "status": x.status, "severity": x.severity} for x in cases],
        },
        "summary": f"{link.name} — {link.tier} tier, customer {cust.name if cust else '—'}, "
                   f"{len(steps)} escalation step(s), {len(cases)} recent case(s).",
    }


def tool_interpret_rsl(rsl_dbm: float, optic_model: str = "") -> dict:
    """Compute the ELNOC optical verdict for an RSL reading (pure code, no tokens)."""
    r = interpret_rsl(rsl_dbm, optic_model)
    return {
        "tool": "interpret_rsl", "rsl_dbm": rsl_dbm, "optic_model": optic_model or "default",
        "status": r["status"], "margin_db": r["margin_db"],
        "fail_floor_dbm": r["limits"]["fail_dbm"],
        "likely_causes": r["likely_causes"],
        "first_checks": r["first_checks"],
        "drift_db": r.get("drift_db"),
        "summary": f"RSL {rsl_dbm} dBm = {r['status']} "
                   f"(margin {r['margin_db']} dB to the {r['limits']['fail_dbm']} dBm fail floor).",
    }


# ---------------------------------------------------------------- write tools (guarded)

def tool_create_case(symptom: str, link_name: str, severity: str = "major",
                     link_state: str = "down", db: Session = None,
                     current_user: str = "") -> dict:
    """Create a new NOC case. Only fires when the user explicitly asks to log one."""
    hit = find_secret(symptom + " " + link_name)
    if hit:
        return {"tool": "create_case", "error": f"Blocked: possible secret ({hit})."}
    link = db.query(Link).filter(Link.name.ilike(f"%{link_name}%")).first()
    if not link:
        return {"tool": "create_case", "error": f"Link “{link_name}” not found — cannot create case."}
    cust = db.get(Customer, link.customer_id) if link.customer_id else None
    case = Case(engineer=current_user or "agent", customer_id=cust.id if cust else None,
                link_id=link.id, symptom=symptom, status="open",
                severity=severity, link_state=link_state, opened_by="agent", opened_at=utcnow())
    db.add(case); db.flush()
    db.add(CaseEvent(case_id=case.id, at=utcnow(), engineer=current_user or "agent",
                     kind="note", text=f"Agent-created case: {symptom}"))
    db.commit()
    return {"tool": "create_case", "case_id": case.id, "link": link.name,
            "customer": cust.name if cust else "—", "symptom": symptom,
            "summary": f"Case #{case.id} created for {link.name} — “{symptom}”."}


def tool_acknowledge_case(case_id: int, db: Session) -> dict:
    """Return escalation/acknowledgement info for a case (read-only hint)."""
    case = db.get(Case, case_id)
    if not case:
        return {"tool": "acknowledge_case", "error": f"Case #{case_id} not found."}
    return {
        "tool": "acknowledge_case", "case_id": case.id,
        "status": case.status, "severity": case.severity,
        "link_state": case.link_state, "engineer": case.engineer,
        "waiting_on": case.waiting_on,
        "summary": f"Case #{case.id} is {case.status} ({case.severity}), owned by {case.engineer or '—'}.",
    }


# ---------------------------------------------------------------- tool registry

TOOL_REGISTRY = {
    "search_playbooks": tool_search_playbooks,
    "check_link": tool_check_link,
    "interpret_rsl": tool_interpret_rsl,
    "create_case": tool_create_case,
    "acknowledge_case": tool_acknowledge_case,
}

TOOL_SCHEMAS = [
    {
        "name": "search_playbooks",
        "description": "Search ELNOC's playbook knowledge base for procedures matching a query.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "What to look up (e.g. 'fibre cut escalation')"},
        }, "required": ["query"]},
    },
    {
        "name": "check_link",
        "description": "Look up a fibre link by name or id: customer, tier, circuit, escalation steps, recent cases.",
        "parameters": {"type": "object", "properties": {
            "link_name_or_id": {"type": "string", "description": "Link name (e.g. 'LTV8 Ikeja-RC') or numeric id"},
        }, "required": ["link_name_or_id"]},
    },
    {
        "name": "interpret_rsl",
        "description": "Compute the ELNOC optical verdict for an RSL reading (FAIL / MARGINAL / OK).",
        "parameters": {"type": "object", "properties": {
            "rsl_dbm": {"type": "number", "description": "Received signal level in dBm, e.g. -29"},
            "optic_model": {"type": "string", "description": "Optic model, e.g. 'GPON-C+' (optional)"},
        }, "required": ["rsl_dbm"]},
    },
    {
        "name": "create_case",
        "description": "Create a new NOC case. Only when the user explicitly asks to log/open one.",
        "parameters": {"type": "object", "properties": {
            "symptom": {"type": "string", "description": "One-line symptom description"},
            "link_name": {"type": "string", "description": "Link name the case is about"},
            "severity": {"type": "string", "description": "L1/L2/L3/Vendor severity (default major)"},
            "link_state": {"type": "string", "description": "Link state, e.g. down/degraded/unstable"},
        }, "required": ["symptom", "link_name"]},
    },
    {
        "name": "acknowledge_case",
        "description": "Get acknowledgement/escalation info for an existing case id.",
        "parameters": {"type": "object", "properties": {
            "case_id": {"type": "integer", "description": "Numeric case id"},
        }, "required": ["case_id"]},
    },
]
