"""Resolve INTO teams — split a handover by who actually has to act.

The handover is one wall of text. Teams want their own slice: paste it into the
group, act, done. So this takes the same cases and re-projects them by the party
that owns the next move.

Who owns a link, in order of truth:
  1. the party we are currently following up with (case.waiting_on)
  2. the link's responsible team
  3. UNASSIGNED — nobody named, so it lands on the NOC to chase

Two rules survive: Phoenix ticket numbers never appear (Q16=A), and the header
always says this is a *direct peek into the handover*, not the handover itself,
so nobody treats the slice as the full picture and stops reading the original.
"""
from __future__ import annotations
from ..models import level_label
from ..services.handover import (fmt_dur, outage_minutes, is_unresolved, is_resolved,
                                 latest_note, _state, assert_no_ticket_leak)
from ..utils_time import to_lagos

UNASSIGNED = "UNASSIGNED \u2014 NOC TO OWN"


def team_for(case, link=None) -> str:
    """The desk this ticket sits on right now."""
    party = (getattr(case, "waiting_on", "") or "").strip()
    if party:
        return party.upper()
    resp = (getattr(link, "responsible_team", "") or "").strip()
    if resp:
        return resp.upper()
    return UNASSIGNED


def _entry(case, link, contacts: dict, now) -> dict:
    name = (getattr(case, "_link_name", "") or case.device or f"CASE-{case.id}").upper()
    # tolerate int or str keys in the contacts map
    contact = contacts.get(case.link_id) or contacts.get(str(case.link_id)) or ""
    return {
        "case_id": case.id,
        "link": name,
        "state": _state(case),
        "state_label": _state(case).upper(),
        "duration": fmt_dur(outage_minutes(case, now)),
        "level": level_label(str(case.escalation_level)
                             if case.escalation_level not in (None, "") else ""),
        "waiting_on": (case.waiting_on or "").upper(),
        "update": (latest_note(case) or "").strip(),
        "affected": [str(a).upper() for a in (getattr(case, "_affected", []) or [])],
        "contact": str(contact).strip(),
        "stale": (getattr(case, "_upd_flag", "") or "").strip(),
        "team": team_for(case, link),
        "resolved": is_resolved(case),
        "severity_rank": {"down": 0, "degraded": 1, "unstable": 2}.get(_state(case), 3),
    }


def build_team_breakdown(cases: list, links: dict | None = None,
                         contacts: dict | None = None, now=None,
                         include_resolved: bool = False) -> dict:
    """-> {teams: [{team, count, entries[]}], order: [team, ...]}"""
    links = links or {}
    contacts = contacts or {}
    groups: dict[str, list[dict]] = {}
    for c in cases:
        if not include_resolved and not is_unresolved(c):
            continue
        link = links.get(c.link_id)
        e = _entry(c, link, contacts, now)
        groups.setdefault(e["team"], []).append(e)

    for entries in groups.values():
        entries.sort(key=lambda e: (e["severity_rank"], e["case_id"]))

    order = sorted(groups, key=lambda t: (len(groups[t]) == 0, t == UNASSIGNED,
                                          -len(groups[t]), t))
    return {
        "teams": [{"team": t, "count": len(groups[t]), "entries": groups[t]}
                  for t in order],
        "order": order,
        "total": sum(len(v) for v in groups.values()),
    }


def render_team_block(team: str, entries: list, meta: dict | None = None) -> str:
    """Paste-ready slice for one team, headed as a peek into the handover."""
    meta = meta or {}
    stamp = to_lagos(meta["now"]).strftime("%H:%M WAT") if meta.get("now") else ""
    hid = meta.get("handover_id")
    date = meta.get("shift_date", "")
    shift = (meta.get("shift") or "").upper()

    head = ["ELNOC \u2013 DIRECT PEEK INTO THE HANDOVER"]
    if hid:
        head[0] += f" #{hid}"
    head.append(f"{date} {shift}".strip() + (f" \u00b7 generated {stamp}" if stamp else ""))
    head.append("NOT the full handover \u2014 only the links on this desk. "
                "The full handover still sits with the NOC.")
    head.append(f"TEAM: {team} \u2014 {len(entries)} "
                f"{'LINK' if len(entries) == 1 else 'LINKS'} NEEDING ACTION")
    head.append("")

    lines = list(head)
    if not entries:
        lines.append("Nothing on this desk right now.")
        assert_no_ticket_leak("\n".join(lines))
        return "\n".join(lines)

    for i, e in enumerate(entries, 1):
        bits = [f"{e['link']} ({e['duration']})", f"STATUS: {e['state_label']}"]
        if e["level"]:
            bits.append(e["level"])
        lines.append(f"{i}. " + " \u2014 ".join(bits))
        if e["waiting_on"]:
            lines.append(f"   WITH: {e['waiting_on']}")
        if e["update"]:
            lines.append(f"   UPDATE: {e['update'][:300]}")
        if e["stale"]:
            lines.append(f"   {e['stale']}")
        if e["affected"]:
            lines.append("   LINKS AFFECTED: " + ", ".join(e["affected"]))
        if e["contact"]:
            lines.append(f"   CLIENT CONTACT: {e['contact']}")
        base = (meta.get("base_url") or "").rstrip("/")
        if base and e["case_id"]:
            lines.append(f"   ELNOC CASE: {base}/cases/{e['case_id']}")
        lines.append("")

    lines.append("Reply here or update the case in ELNOC \u2014 the handover "
                 "regenerates from the same data.")
    text = "\n".join(lines)
    assert_no_ticket_leak(text)
    return text