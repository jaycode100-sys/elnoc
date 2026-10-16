"""UTC store / Africa/Lagos display (NFR-12)."""
from __future__ import annotations
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

LAGOS = ZoneInfo("Africa/Lagos")

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

def to_lagos(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(LAGOS)

def fmt_wat(dt: datetime) -> str:
    """DD/MM/YYYY HH:MM WAT e.g. 11/10/2026 22:14 WAT"""
    return to_lagos(dt).strftime("%d/%m/%Y %H:%M WAT")

def fmt_date(dt: datetime) -> str:
    return to_lagos(dt).strftime("%d/%m/%Y")

def ensure_utc(dt: datetime) -> datetime:
    if dt is None:
        return utcnow()
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def age_minutes(since: datetime, now: datetime | None = None) -> int:
    now = now or utcnow()
    return max(0, int((ensure_utc(now) - ensure_utc(since)).total_seconds() // 60))
