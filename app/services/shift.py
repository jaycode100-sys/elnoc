"""Shared shift helpers — single source of truth for date handling,
shift labelling, power-source constants, and battery/time parsing.

Used by both `app/routers/myshift.py` and `app/routers/power.py` so the two
routers can never diverge on date formats or shift boundaries.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional

from sqlalchemy.orm import Session

from ..utils_time import utcnow, to_lagos

POWER_SOURCES = ("light", "big generator", "small generator", "inverter", "solar", "power tank")


def lagos_date_iso() -> str:
    """Today's date in Lagos as ISO YYYY-MM-DD (canonical internal format)."""
    return to_lagos(utcnow()).strftime("%Y-%m-%d")


def lagos_date_display(iso_date: str) -> str:
    """Format ISO YYYY-MM-DD as DD/MM/YYYY for display."""
    parts = iso_date.split("-")
    return f"{parts[2]}/{parts[1]}/{parts[0]}" if len(parts) == 3 else iso_date


def parse_lagos_date(value: str) -> str:
    """Accept either ISO (YYYY-MM-DD) or legacy DD/MM/YYYY; return ISO."""
    value = value.strip()
    if "/" in value:
        parts = value.split("/")
        if len(parts) == 3:
            return f"{parts[2]}-{parts[1]}-{parts[0]}"
    # Already ISO — validate
    date.fromisoformat(value)
    return value


def shift_label(now: datetime | None = None) -> str:
    """day (07:00–18:59 Lagos) or night (19:00–06:59 Lagos)."""
    now = now or utcnow()
    lagos = to_lagos(now)
    return "day" if 7 <= lagos.hour < 19 else "night"


def shift_label_from_roster(db: Session, engineer: str, date_iso: str) -> str:
    """Shift label from the roster if an entry exists, else from the clock."""
    from ..models import ShiftRoster
    row = db.query(ShiftRoster).filter(
        ShiftRoster.engineer == engineer,
        ShiftRoster.shift_date == date_iso,
    ).first()
    if row:
        return row.shift
    return shift_label()


def shift_label_from_date(date_iso: str) -> str:
    """Shift label for a given date — always 'day' for past dates (label is
    computed at save time). Kept for API symmetry."""
    return "day"


def parse_battery_level(text: str) -> str:
    """Return the battery level portion of a raw line, best effort.

    Examples:
      "Inverter: 24%, Kitchen: 44%, Office: 39%" -> "24%, Kitchen: 44%, Office: 39%"
      "71%" -> "71%"
    """
    m = re.search(r"(?:battery|level|inverter|solar|tank)[^0-9]*([0-9]+%(?:[^0-9]*[0-9]+%)*)", text, re.I)
    if m:
        return m.group(1).strip()
    m = re.search(r"([0-9]{1,3}%)", text)
    return m.group(1) if m else ""


def parse_time(text: str) -> str:
    """Extract HH:MM AM/PM from a raw text line."""
    m = re.search(r"(\d{1,2}:\d{2}\s*(?:AM|PM))", text, re.I)
    return m.group(1).upper() if m else ""


def infer_activity(text: str) -> str:
    """Infer a short activity phrase from free text."""
    t = text.lower()
    for src in POWER_SOURCES:
        if src in t:
            for verb in ("switched on", "switched off", "came on", "went off",
                         "restored", "failed", "tripped"):
                if verb in t:
                    return f"{src.title()} {verb.title()}"
            return f"{src.title()} event"
    if "generator" in t:
        return "Generator event"
    if "inverter" in t:
        return "Inverter event"
    if "solar" in t:
        return "Solar event"
    if "tank" in t or "battery" in t:
        return "Power tank / battery event"
    if "light" in t or "power" in t or "electric" in t or "supply" in t:
        return "Mains power event"
    return "Power event"
