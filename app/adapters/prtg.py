"""PRTG adapter (FR-01). Poll /api/table.json for all sensors, split locally.

Fixes gap #1 (stable occurred_at) and #2 (recoveries were sliced to [:0]).
NOTE: no server-side status filter — recoveries (Up) must come back in the
same poll or FR-08 notes never attach. Pilot-scale PRTG handles this fine;
past ~10k sensors, switch to two filtered calls (Down + Up) instead.
"""
from __future__ import annotations
import json, re, urllib.request, urllib.parse
from datetime import datetime, timezone
from .base import RawEvent
from ..config import settings
from ..utils_time import utcnow

RSL_RX = re.compile(r"(-?\d+(?:\.\d+)?)\s*dBm", re.IGNORECASE)

def parse_rsl(text: str | None) -> float | None:
    """Optical level hiding in a sensor message, e.g. 'RSL -21.3 dBm'. FR-82."""
    if not text:
        return None
    m = RSL_RX.search(text)
    if not m:
        return None
    try:
        v = float(m.group(1))
    except ValueError:
        return None
    return v if -60.0 <= v <= 10.0 else None  # sanity: reject stray numbers

def _parse_prtg_time(s: str | None) -> datetime:
    if not s:
        return utcnow()  # first-seen fallback kept OUT of fingerprint day? fingerprint uses day only
    try:
        # PRTG returns 'DD/MM/YYYY HH:MM:SS AM/PM' or ISO depending on call
        for fmt in ("%d/%m/%Y %I:%M:%S %p", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.strptime(s.strip(), fmt)
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return utcnow()
    except Exception:
        return utcnow()

def collect_prtg(fetcher=None) -> list[RawEvent]:
    """fetcher: injectable for tests -> returns list of sensor dicts."""
    if fetcher is not None:
        sensors = fetcher()
    else:
        if not settings.PRTG_BASE_URL:
            return []
        params = urllib.parse.urlencode({
            "content": "sensors", "output": "json",
            "columns": "objid,device,sensor,status,lastup,lastdown,message",
            "username": settings.PRTG_USERNAME, "passhash": settings.PRTG_PASSHASH,
        })
        url = settings.PRTG_BASE_URL.rstrip("/") + f"/api/table.json?{params}"
        with urllib.request.urlopen(url, timeout=30) as r:
            payload = json.loads(r.read().decode())
        sensors = payload.get("sensors", [])
    events: list[RawEvent] = []
    for s in sensors:
        status = str(s.get("status", "")).strip()
        device = str(s.get("device", "") or s.get("host", "")).strip()
        name = str(s.get("sensor", "") or s.get("name", "")).strip()
        rsl = parse_rsl(f"{s.get('message','')} {name}")
        if status.lower() in ("down", "5"):
            events.append(RawEvent(
                source="PRTG", etype="down", device=device or name,
                summary=f"Sensor DOWN: {name} on {device}. {s.get('message','')}".strip(),
                severity="critical",
                occurred_at=_parse_prtg_time(s.get("lastdown") or s.get("lastup")),
                ref=str(s.get("objid", "")), raw=json.dumps(s)[:2000],
                rsl_dbm=rsl))
        elif status.lower() in ("up", "3", "ok"):
            # recovery: attach to open case, never silently close (FR-08)
            events.append(RawEvent(
                source="PRTG", etype="up", device=device or name,
                summary=f"Sensor UP (recovery): {name} on {device}",
                severity="info",
                occurred_at=_parse_prtg_time(s.get("lastup")),
                ref=str(s.get("objid", "")), raw=json.dumps(s)[:2000],
                rsl_dbm=rsl))
    # NOTE: old script sliced recovery loop to [:0] — fixed here: all recoveries emitted.
    return events
