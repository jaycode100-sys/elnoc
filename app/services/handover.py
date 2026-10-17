"""Handover builder — team format (FR-40..FR-47) + the detailed summary block.

Rules that matter:
- Phoenix ticket numbers are APP-ONLY. They never enter this text (the team
  reads tickets in Phoenix); `assert_no_ticket_leak` enforces it.
- Link states: DOWN / DEGRADED / UNSTABLE / UP. Anything else falls back to
  DOWN so nothing silently disappears from the unresolved list.
- The summary block at the end is what the incoming shift scans first: tally
  per state, who was on duty, and the current restoration picture.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import timedelta
from ..utils_time import fmt_date, age_minutes, utcnow, ensure_utc, to_lagos

DIVIDER = "-------------------------------------------------"

STATES = ("down", "degraded", "unstable", "up")


def _state(case) -> str:
    s = (case.link_state or "").strip().lower()
    return s if s in STATES else "down"


def is_unresolved(case) -> bool:
    return _state(case) != "up" and case.status != "resolved"


def is_resolved(case) -> bool:
    return not is_unresolved(case)


def build_handover_text(cases: list, shift_date_str: str, show_wait_age: bool = False,
                        now=None, stale_map: dict | None = None,
                        resolved_notes: bool = False,
                        summary: bool = True,
                        from_engineer: str = "", to_engineer: str = "",
                        restored_hours: int = 12) -> str:
    """cases: Case objects with optional ._link_name / ._latest_note / ._affected.

    stale_map: {case_id: "⚠ SAME UPDATE …"} appended after a bar (team's own
    convention) — off by default so the text stays byte-identical to the
    11-Oct sample. resolved_notes: append " | <note>" on resolved entries
    (the 16-Oct real format); off by default for the same reason.
    summary: append the detailed SHIFT SUMMARY block (counts, duty engineer,
    restoration). Off reproduces the classic text exactly.
    """
    now = now or utcnow()
    stale_map = stale_map or {}
    unresolved = [c for c in cases if is_unresolved(c)]
    resolved = [c for c in cases if is_resolved(c)]

    def order_key(c):
        rank = {"down": 0, "degraded": 1, "unstable": 2, "up": 3}.get(_state(c), 4)
        return (rank, c.id)
    unresolved.sort(key=order_key)
    resolved.sort(key=lambda c: c.id)

    lines = [f"TICKET UPDATES \u2013 {shift_date_str}", "UNRESOLVED LINKS", ""]
    for c in unresolved:
        lname = getattr(c, "_link_name", "") or f"CASE-{c.id}"
        lines.append(lname.upper())
        lines.append(f"STATUS: {_state(c).upper()}")
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
    text = "\n".join(lines).rstrip() + "\n"

    if summary:
        text += "\n" + build_summary(cases, shift_date_str, now=now,
                                     from_engineer=from_engineer,
                                     to_engineer=to_engineer,
                                     restored_hours=restored_hours)
    assert_no_ticket_leak(text)
    return text


def build_summary(cases: list, shift_date_str: str, now=None,
                  from_engineer: str = "", to_engineer: str = "",
                  restored_hours: int = 12) -> str:
    """The block the incoming shift reads first: what state, who was on duty,
    what got restored and when, and what is still burning."""
    now = now or utcnow()
    tally = {"down": 0, "degraded": 0, "unstable": 0, "up": 0}
    for c in cases:
        tally[_state(c)] += 1

    cutoff = ensure_utc(now) - timedelta(hours=restored_hours)
    restored = [c for c in cases
                if c.restored_at and ensure_utc(c.restored_at) >= cutoff]
    restored.sort(key=lambda c: ensure_utc(c.restored_at), reverse=True)

    still = [c for c in cases if is_unresolved(c)]
    still.sort(key=lambda c: age_minutes(c.opened_at, now), reverse=True)

    out = [DIVIDER, f"SHIFT SUMMARY \u2013 {shift_date_str}"]
    out.append("ON SHIFT DUTY: "
               + (from_engineer.upper() if from_engineer else "NOT RECORDED")
               + ("  \u2192 INCOMING: " + to_engineer.upper() if to_engineer else ""))
    out.append(f"TICKETS THIS HANDOVER: {len(cases)}"
               f"  (DOWN {tally['down']} \u00b7 DEGRADED {tally['degraded']}"
               f" \u00b7 UNSTABLE {tally['unstable']} \u00b7 UP {tally['up']})")

    out.append("")
    out.append(f"LINK RESTORATION UPDATE (LAST {restored_hours}H)")
    if restored:
        for c in restored[:15]:
            when = to_lagos(ensure_utc(c.restored_at)).strftime("%d/%m %H:%M WAT")
            name = (getattr(c, "_link_name", "") or f"CASE-{c.id}").upper()
            cause = (getattr(c, "fix", "") or latest_note(c) or "").strip()
            out.append(f"- {name} \u2013 UP {when}"
                       + (f" \u2013 {cause[:120]}" if cause else ""))
        if len(restored) > 15:
            out.append(f"- …and {len(restored) - 15} more restored (see app)")
    else:
        out.append("- NONE RESTORED IN THIS WINDOW")

    out.append("")
    out.append(f"STILL UNRESOLVED AT HANDOVER: {len(still)}")
    for c in still[:15]:
        age_h = age_minutes(c.opened_at, now) // 60
        age_txt = f"{age_h}h" if age_h >= 1 else f"{age_minutes(c.opened_at, now)}m"
        name = (getattr(c, "_link_name", "") or f"CASE-{c.id}").upper()
        party = (c.waiting_on or "NOBODY NAMED").upper()
        lvl = f" [{c.escalation_level}]" if c.escalation_level else ""
        out.append(f"- {name} ({_state(c).upper()}{lvl}, {age_txt}) \u2013 WITH {party}")
    if len(still) > 15:
        out.append(f"- …and {len(still) - 15} more (see app)")
    return "\n".join(out) + "\n"


def ticket_numbers(cases: list) -> set[str]:
    return {(c.phoenix_ticket_no or "").strip() for c in cases
            if (c.phoenix_ticket_no or "").strip()}


def assert_no_ticket_leak(text: str) -> None:
    """Phoenix refs must never appear in the handover (app-only rule)."""
    for line in text.splitlines():
        low = line.lower()
        if "phoenix" in low or "ticket no" in low or "ticket #" in low:
            raise ValueError(f"ticket reference leaked into handover: {line[:120]}")


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