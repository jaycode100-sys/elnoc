"""Handover builder — configured format (MCQ answers, Oct 2026).

Layout (Q1,Q2): header -> SHIFT SUMMARY -> UNRESOLVED (sub-headed by state)
-> RESOLVED. Durations beside every incident (Q3 note), long form (Q14=B),
levels in words (Q15=C), second fact on its own NOTE: line instead of the bar
(Q20=C), stale flags ON in the text (Q21=B), one divider before the summary
(Q23=B).

Two hard rules survive all formatting: Phoenix ticket numbers never appear
here (Q16=A), and an unknown state falls back to DOWN so nothing disappears.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import timedelta
from ..models import level_label
from ..services.shift import lagos_date_display
from ..utils_time import fmt_date, age_minutes, utcnow, ensure_utc, to_lagos

DIVIDER = "-------------------------------------------------"
STATES = ("down", "degraded", "unstable", "up")
STATE_HEADINGS = {"down": "DOWN", "degraded": "DEGRADED", "unstable": "UNSTABLE"}


def _state(case) -> str:
    s = (case.link_state or "").strip().lower()
    return s if s in STATES else "down"


def is_unresolved(case) -> bool:
    return _state(case) != "up" and case.status != "resolved"


def is_resolved(case) -> bool:
    return not is_unresolved(case)


def fmt_dur(minutes: int) -> str:
    """Q14=B: long form — '5H 12M', '45M', '0M'."""
    minutes = max(0, int(minutes or 0))
    h, m = divmod(minutes, 60)
    return f"{h}H {m}M" if h else f"{m}M"


def outage_minutes(case, now=None) -> int:
    """Duration of THIS outage — from when the fault began, else case open."""
    now = now or utcnow()
    start = case.outage_start or case.opened_at
    try:
        return age_minutes(start, now)
    except Exception:
        return 0


def _restore_minutes(case, now=None) -> int:
    if not case.opened_at:
        return 0
    end = case.restored_at or case.closed_at or utcnow()
    return age_minutes(case.opened_at, end)


def build_handover_text(cases: list, shift_date_str: str, show_wait_age: bool = False,
                        now=None, stale_map: dict | None = None,
                        resolved_notes: bool = False,
                        summary: bool = True,
                        from_engineer: str = "", to_engineer: str = "",
                        restored_hours: int = 12,
                        header_time: str = "") -> str:
    """cases: Case objects with optional ._link_name / ._latest_note / ._affected."""
    now = now or utcnow()
    stale_map = stale_map or {}
    unresolved = [c for c in cases if is_unresolved(c)]
    resolved = [c for c in cases if is_resolved(c)]

    def order_key(c):
        rank = {"down": 0, "degraded": 1, "unstable": 2}.get(_state(c), 4)
        return (rank, age_minutes(c.opened_at or now, now), c.id)
    unresolved.sort(key=order_key)
    resolved.sort(key=lambda c: c.id)

    stamp = header_time or to_lagos(now).strftime("%H:%M WAT")
    # Q1=B: NOC HANDOVER - date + time (date from the handover, time live)
    lines = [f"NOC HANDOVER \u2013 {shift_date_str} {stamp}", ""]

    if summary:
        # Q23=B: the only divider, immediately before the summary
        lines.append(DIVIDER)
        lines.extend(build_summary(cases, shift_date_str, now=now,
                                   from_engineer=from_engineer,
                                   to_engineer=to_engineer,
                                   restored_hours=restored_hours).splitlines())
        lines.append("")

    lines.append("UNRESOLVED LINKS")
    lines.append("")
    # Q3 note: sub-headers divide the tickets by state
    grouped = defaultdict(list)
    for c in unresolved:
        grouped[_state(c)].append(c)
    if not unresolved:
        lines.append("NONE \u2013 ALL LINKS CLEAR")
        lines.append("")
    for state in ("down", "degraded", "unstable"):
        group = grouped.get(state) or []
        if not group:
            continue
        lines.append(f"{STATE_HEADINGS[state]} ({len(group)})")
        lines.append("")
        for c in group:
            _entry(lines, c, now, stale_map, show_wait_age)

    lines.append("RESOLVED LINKS")
    lines.append("")
    if not resolved:
        lines.append("NONE RESTORED IN THIS HANDOVER")
    for c in resolved:
        lname = (getattr(c, "_link_name", "") or f"CASE-{c.id}").upper()
        lines.append(f"{lname} ({fmt_dur(_restore_minutes(c, now))})")
        status_line = "STATUS: UP"
        if resolved_notes:
            note = (latest_note(c) or getattr(c, "fix", "") or "").strip()
            if note:
                status_line += f" | {note[:160]}"
        lines.append(status_line)
    text = "\n".join(lines).rstrip() + "\n"
    assert_no_ticket_leak(text)
    return text


def _entry(lines: list, c, now, stale_map: dict, show_wait_age: bool) -> None:
    """One unresolved ticket: name + duration, STATUS, UPDATE, NOTE, affected."""
    lname = (getattr(c, "_link_name", "") or f"CASE-{c.id}").upper()
    dur = fmt_dur(outage_minutes(c, now))
    lines.append(f"{lname} ({dur})")
    lines.append(f"STATUS: {_state(c).upper()}")
    note = (latest_note(c) or "").strip()
    if c.waiting_on:
        upd = f"UPDATE: FOLLOWING UP WITH {c.waiting_on.upper()}"
    else:
        # no owner: say so loudly whether or not there is a note to carry
        upd = f"UPDATE: {note}" if note else "UPDATE: "
        upd += "NO PARTY NAMED \u2013 ESCALATE NOW"
        note = ""
    if show_wait_age:
        upd += f" [{fmt_dur(age_minutes(c.opened_at, now))} WAITING]"
    flag = stale_map.get(getattr(c, "id", None))
    if flag:
        upd += f" | {flag}"
    lines.append(upd)
    # Q20=C: the extra fact gets its own NOTE: line, not the bar
    if note and c.waiting_on:
        lines.append(f"NOTE: {note[:300]}")
    lvl = level_label(c.escalation_level)
    if lvl:
        lines.append(f"LEVEL: {lvl}")
    aff = getattr(c, "_affected", []) or []
    if aff:
        lines.append("LINKS AFFECTED")
        lines.append(", ".join(a.upper() for a in aff))
    lines.append("")


def build_summary(cases: list, shift_date_str: str, now=None,
                  from_engineer: str = "", to_engineer: str = "",
                  restored_hours: int = 12) -> str:
    """Tally (Q7=A), duty engineer (Q8=A), restoration (Q10/11/12=A),
    still-unresolved with level+age+party (Q13=A), long ages (Q14=B)."""
    now = now or utcnow()
    tally = {"down": 0, "degraded": 0, "unstable": 0, "up": 0}
    for c in cases:
        tally[_state(c)] += 1

    cutoff = ensure_utc(now) - timedelta(hours=restored_hours)
    restored = [c for c in cases
                if c.restored_at and ensure_utc(c.restored_at) >= cutoff]
    restored.sort(key=lambda c: ensure_utc(c.restored_at), reverse=True)

    still = [c for c in cases if is_unresolved(c)]
    still.sort(key=lambda c: outage_minutes(c, now), reverse=True)

    out = ["SHIFT SUMMARY \u2013 " + shift_date_str]
    # Q8=A
    out.append("ON SHIFT DUTY: "
               + (from_engineer.upper() if from_engineer else "NOT RECORDED")
               + ("  \u2192 INCOMING: " + to_engineer.upper() if to_engineer else ""))
    # Q7=A
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
        name = (getattr(c, "_link_name", "") or f"CASE-{c.id}").upper()
        party = (c.waiting_on or "NOBODY NAMED").upper()
        lvl = level_label(c.escalation_level)
        lvl_txt = f" — {lvl}" if lvl else ""
        out.append(f"- {name} ({_state(c).upper()}{lvl_txt}, "
                   f"{fmt_dur(outage_minutes(c, now))}) \u2013 WITH {party}")
    if len(still) > 15:
        out.append(f"- …and {len(still) - 15} more (see app)")
    return "\n".join(out)


def ticket_numbers(cases: list) -> set[str]:
    return {(c.phoenix_ticket_no or "").strip() for c in cases
            if (c.phoenix_ticket_no or "").strip()}


def assert_no_ticket_leak(text: str) -> None:
    """Phoenix refs must never appear in the handover (Q16=A, app-only)."""
    for line in text.splitlines():
        low = line.lower()
        if "phoenix" in low or "ticket no" in low or "ticket #" in low:
            raise ValueError(f"ticket reference leaked into handover: {line[:120]}")


def latest_note(case) -> str:
    if getattr(case, "_latest_note", None):
        return case._latest_note
    return case.symptom or ""


def group_by_waiting_party(cases: list) -> dict[str, list]:
    groups: dict[str, list] = defaultdict(list)
    for c in cases:
        if c.status == "waiting_other_team" or c.waiting_on:
            groups[(c.waiting_on or "UNASSIGNED").upper()].append(c)
    return dict(groups)


def append_shift_summary(db: Session, engineer: str, date_iso: str, shift: str,
                         notes: list, power_report_id: int | None = None) -> str:
    """Append a shift summary section to the handover document when a shift closes.

    Returns the appended summary text. Callers should append this to the
    handover document and persist it.
    """
    from ..models import ShiftNote, PowerReport

    # Gather this engineer's notes for the shift
    shift_notes = db.query(ShiftNote).filter(
        ShiftNote.engineer == engineer,
        ShiftNote.shift_date == date_iso,
        ShiftNote.shift == shift).order_by(
        ShiftNote.created_at.asc()).all()

    # Gather power reports for the date
    power_reports = db.query(PowerReport).filter(
        PowerReport.report_date == date_iso).order_by(
        PowerReport.created_at.asc()).all()

    lines = []
    lines.append("")
    lines.append(DIVIDER)
    lines.append("SHIFT SUMMARY — " + lagos_date_display(date_iso) + " " + shift.upper())
    lines.append("")
    lines.append(f"ENGINEER: {engineer}")
    lines.append("")
    if shift_notes:
        lines.append("NOTES:")
        for n in shift_notes:
            when = n.created_at.strftime("%H:%M") if n.created_at else ""
            lines.append(f"- [{when}] {n.notes}")
            if n.extra_info:
                lines.append(f"  Extra: {n.extra_info}")
            if n.power_status:
                lines.append(f"  Power: {n.power_status}")
        lines.append("")
    else:
        lines.append("NOTES: (nothing to report)")
        lines.append("")
    if power_reports:
        lines.append("POWER EVENTS:")
        for pr in power_reports:
            when = pr.event_time or "time not stated"
            batt = pr.battery_level or "level not stated"
            lines.append(f"- [{when}] {pr.activity} — {batt}")
        lines.append("")
    lines.append("END OF SHIFT SUMMARY")
    lines.append("")
    return "\n".join(lines)
