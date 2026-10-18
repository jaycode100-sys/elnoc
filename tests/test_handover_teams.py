"""Resolve INTO teams: the handover re-projected by who has to act."""
from __future__ import annotations
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import handover_teams as ht  # noqa: E402

NOW = datetime(2026, 10, 18, 14, 0, tzinfo=timezone.utc)


class Link:
    def __init__(self, id, name, team=""):
        self.id, self.name, self.responsible_team = id, name, team


class Case:
    def __init__(self, id, link_id, device="", link_state="down", status="open",
                 waiting_on="", opened_at=None, escalation_level=1,
                 phoenix_ticket_no="", fix="", _link_name="", _affected=None,
                 _upd_flag="", symptom=""):
        self.id = id
        self.link_id = link_id
        self.device = device
        self.link_state = link_state
        self.status = status
        self.waiting_on = waiting_on
        self.opened_at = opened_at or (NOW - timedelta(hours=2))
        self.escalation_level = escalation_level
        self.phoenix_ticket_no = phoenix_ticket_no
        self.fix = fix
        self.symptom = symptom
        self._link_name = _link_name or f"link-{link_id}"
        self._affected = _affected or []
        self._upd_flag = _upd_flag
        self._latest_note = ""

    def __getattr__(self, item):
        if item in ("restored_at", "closed_at", "outage_start"):
            return None
        raise AttributeError(item)


def test_team_prefers_waiting_party():
    lk = Link(1, "L1", "Fibre Team")
    assert ht.team_for(Case(1, 1, waiting_on="Prec Pearl"), lk) == "PREC PEARL"
    # no party -> the link's responsible team
    assert ht.team_for(Case(2, 1), lk) == "FIBRE TEAM"
    # neither -> NOC owns it
    assert ht.team_for(Case(3, 1), Link(1, "L1")) == ht.UNASSIGNED


def test_grouping_and_ordering():
    links = {1: Link(1, "Levene"), 2: Link(2, "Oregun"), 3: Link(3, "Prec")}
    cases = [
        Case(1, 1, waiting_on="Prec Pearl"),
        Case(2, 2, waiting_on="Prec Pearl"),
        Case(3, 3, waiting_on="Prec Pearl"),
        Case(4, 1, waiting_on="Oregun Team", link_state="degraded"),
        Case(5, 1),
    ]
    bd = ht.build_team_breakdown(cases, links, now=NOW)
    by_team = {g["team"]: g["count"] for g in bd["teams"]}
    assert by_team == {"PREC PEARL": 3, ht.UNASSIGNED: 1, "OREGUN TEAM": 1}
    # busiest first, unassigned last
    assert bd["order"][0] == "PREC PEARL"
    assert bd["order"][-1] == ht.UNASSIGNED
    assert bd["total"] == 5


def test_resolved_cases_excluded_by_default():
    links = {1: Link(1, "L1")}
    cases = [Case(1, 1, waiting_on="Team A", status="resolved", link_state="up")]
    assert ht.build_team_breakdown(cases, links, now=NOW)["total"] == 0
    assert ht.build_team_breakdown(cases, links, now=NOW,
                                   include_resolved=True)["total"] == 1


def test_worst_state_first_inside_a_desk():
    links = {1: Link(1, "L1")}
    cases = [Case(1, 1, waiting_on="T", link_state="unstable"),
             Case(2, 1, waiting_on="T", link_state="down"),
             Case(3, 1, waiting_on="T", link_state="degraded")]
    entries = ht.build_team_breakdown(cases, links, now=NOW)["teams"][0]["entries"]
    assert [e["state"] for e in entries] == ["down", "degraded", "unstable"]


def test_block_header_says_direct_peek_not_full_handover():
    links = {1: Link(1, "Levene")}
    cases = [Case(1, 1, waiting_on="Prec Pearl", _link_name="Levene Lcon",
                  _affected=["Levene Lcon", "Oregun X"], symptom="awaiting access")]
    bd = ht.build_team_breakdown(cases, links, {"1": "Mr Adekunle — WhatsApp +2"},
                                 now=NOW)
    text = ht.render_team_block("PREC PEARL", bd["teams"][0]["entries"],
                                {"now": NOW, "handover_id": 12,
                                 "shift_date": "2026-10-18", "shift": "day",
                                 "base_url": "https://elnoc.example"})
    assert "DIRECT PEEK INTO THE HANDOVER #12" in text
    assert "NOT the full handover" in text
    assert "TEAM: PREC PEARL — 1 LINK NEEDING ACTION" in text
    assert "LEVENE LCON (2H 0M)" in text
    assert "STATUS: DOWN" in text
    assert "WITH: PREC PEARL" in text
    assert "LINKS AFFECTED: LEVENE LCON, OREGUN X" in text
    assert "CLIENT CONTACT: Mr Adekunle" in text
    assert "https://elnoc.example/cases/1" in text


def test_pluralisation_single_link():
    entries = ht.build_team_breakdown(
        [Case(1, 1, waiting_on="T")], {1: Link(1, "L")}, now=NOW
    )["teams"][0]["entries"]
    assert "1 LINK NEEDING ACTION" in ht.render_team_block("T", entries)


def test_empty_desk_says_so():
    text = ht.render_team_block("OREGUN TEAM", [])
    assert "Nothing on this desk right now." in text
    assert "DIRECT PEEK INTO THE HANDOVER" in text


def test_ticket_numbers_never_leak():
    links = {1: Link(1, "L1")}
    cases = [Case(1, 1, waiting_on="T", _link_name="Levene Lcon",
                  phoenix_ticket_no="PHX-9981")]
    entries = ht.build_team_breakdown(cases, links, now=NOW)["teams"][0]["entries"]
    text = ht.render_team_block("T", entries)
    assert "PHX-9981" not in text


def test_injected_note_leak_is_blocked():
    """A note containing a ticket ref must raise, not silently ship."""
    links = {1: Link(1, "L1")}
    cases = [Case(1, 1, waiting_on="T", symptom="see Phoenix ticket no 445")]
    entries = ht.build_team_breakdown(cases, links, now=NOW)["teams"][0]["entries"]
    with pytest.raises(ValueError):
        ht.render_team_block("T", entries)


def test_duration_and_level_carried():
    links = {1: Link(1, "L1")}
    c = Case(1, 1, waiting_on="T", opened_at=NOW - timedelta(hours=5, minutes=12),
             escalation_level=2)
    e = ht.build_team_breakdown([c], links, now=NOW)["teams"][0]["entries"][0]
    assert e["duration"] == "5H 12M"
    assert e["level"]


def test_stale_flag_surfaced():
    links = {1: Link(1, "L1")}
    c = Case(1, 1, waiting_on="T", _upd_flag="REPEAT UPDATE — ask for a fresh finding")
    entries = ht.build_team_breakdown([c], links, now=NOW)["teams"][0]["entries"]
    assert "ask for a fresh finding" in ht.render_team_block("T", entries)