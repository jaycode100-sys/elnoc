"""Handover builder — exact 11-Oct-2026 team format (FR-40..FR-47)."""
from __future__ import annotations
from collections import defaultdict
from ..utils_time import fmt_date, age_minutes, utcnow

DIVIDER = "-------------------------------------------------"

def build_handover_text(cases: list, shift_date_str: str, show_wait_age: bool = False,
                        now=None, stale_map: dict | None = None,
                        resolved_notes: bool = False) -> str:
    """cases: list of Case objects (with link_name/customer attrs attached as ._link_name).

    stale_map: {case_id: "⚠ SAME UPDATE …"} appended after a bar (team's own
    convention) — off by default so the text stays byte-identical to the
    11-Oct sample. resolved_notes: append " | <note>" on resolved entries
    (the 16-Oct real format); off by default for the same reason.
    """
    now = now or utcnow()
    stale_map = stale_map or {}
    unresolved = [c for c in cases if (c.link_state or "").lower() in ("down", "degraded") and c.status != "resolved"]
    resolved = [c for c in cases if (c.link_state or "").lower() == "up" or c.status == "resolved"]

    def order_key(c):
        rank = {"down": 0, "degraded": 1, "up": 2}.get((c.link_state or "").lower(), 3)
        return (rank, c.id)
    unresolved.sort(key=order_key)
    resolved.sort(key=lambda c: c.id)

    lines = [f"TICKET UPDATES \u2013 {shift_date_str}", "UNRESOLVED LINKS", ""]
    # affected-link lookup attached by caller as ._affected: dict case_id -> [names]
    for c in unresolved:
        lname = getattr(c, "_link_name", "") or f"CASE-{c.id}"
        lines.append(lname.upper())
        lines.append(f"STATUS: {(c.link_state or '').upper()}")
        note = (latest_note(c) or "").strip()
        if c.waiting_on:
            upd = f"UPDATE: FOLLOWING UP WITH {c.waiting_on.upper()}"
            if note:
                upd += f" | {note}"
        else:
            upd = f"UPDATE: {note}" if note else "UPDATE: "
        if show_wait_age:
            upd += f" [{age_minutes(c.opened_at, now)}m waiting]"
        flag = stale_map.get(getattr(c, "id", None))
        if flag:
            upd += f" | {flag}"
        lines.append(upd)
        aff = getattr(c, "_affected", []) or []
        if aff:
            lines.append("LINKS AFFECTED")
            lines.append(", ".join(a.upper() for a in aff))
        lines.append(DIVIDER)
        lines.append("")
    lines.append("RESOLVED LINKS")
    lines.append("")
    for c in resolved:
        lname = getattr(c, "_link_name", "") or f"CASE-{c.id}"
        lines.append(lname.upper())
        status_line = "STATUS: UP"
        if resolved_notes:
            note = (latest_note(c) or getattr(c, "fix", "") or "").strip()
            if note:
                status_line += f" | {note[:160]}"
        lines.append(status_line)
    return "\n".join(lines).rstrip() + "\n"

def latest_note(case) -> str:
    # caller may attach ._latest_note; else fall back to symptom/fix
    if getattr(case, "_latest_note", None):
        return case._latest_note
    return case.symptom or ""

def group_by_waiting_party(cases: list) -> dict[str, list]:
    groups: dict[str, list] = defaultdict(list)
    for c in cases:
        if c.status == "waiting_other_team" or c.waiting_on:
            groups[(c.waiting_on or "UNASSIGNED").upper()].append(c)
    return dict(groups)
