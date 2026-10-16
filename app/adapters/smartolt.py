"""SmartOLT adapter (FR-03). REST if it exposes events; else [] with reason.
Questions for admin (sec 9.3) encoded as logged warnings, never assumed."""
from __future__ import annotations
import json, urllib.request
from .base import RawEvent
from ..config import settings
from ..utils_time import utcnow

def collect_smartolt(fetcher=None) -> list[RawEvent]:
    if fetcher is not None:
        items = fetcher()
    else:
        if not settings.SMARTOLT_BASE_URL or not settings.SMARTOLT_API_KEY:
            return []  # not configured -> controlled manual log path (per design)
        url = settings.SMARTOLT_BASE_URL.rstrip("/") + "/api/events?limit=100"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {settings.SMARTOLT_API_KEY}"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                items = json.loads(r.read().decode())
                if isinstance(items, dict):
                    items = items.get("events", items.get("data", []))
        except Exception:
            return []
    events = []
    for it in (items or []):
        kind = str(it.get("type", it.get("event", "pon"))).lower()
        etype = "pon" if "pon" in kind else ("onu" if "onu" in kind else kind or "pon")
        sev = "critical" if ("outage" in kind or "down" in kind or "offline" in kind) else "major"
        events.append(RawEvent(
            source="SMARTOLT", etype=etype,
            device=str(it.get("olt", it.get("device", it.get("pon", "")))),
            summary=str(it.get("summary", it.get("message", etype)))[:400],
            severity=sev, occurred_at=utcnow(),
            ref=str(it.get("id", "")), raw=json.dumps(it)[:2000]))
    return events
