"""Zabbix adapter (FR-02). Fixes gap #3: device from host, not problem name; no `recent`."""
from __future__ import annotations
import json, urllib.request
from datetime import datetime, timezone
from .base import RawEvent
from ..config import settings

def _sev_map(zabbix_priority: int) -> str:
    try:
        p = int(zabbix_priority)
    except Exception:
        return "major"
    return "critical" if p >= 4 else ("major" if p >= 2 else "minor")

def _rpc(method: str, params: dict, auth: str | None) -> dict:
    payload = {"jsonrpc": "2.0", "method": method, "id": 1, "params": params}
    if auth:
        payload["auth"] = auth
    req = urllib.request.Request(settings.ZABBIX_BASE_URL.rstrip("/") + "/api_jsonrpc.php",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode())
    # Never swallow API errors: bad token / bad login / no permission must
    # show up on the collector-status page (gap #10), not as a silent [].
    if isinstance(data, dict) and "error" in data:
        err = data["error"]
        raise RuntimeError(f"Zabbix API error on {method}: "
                           f"{err.get('message', err)} {err.get('data', '')}"[:300])
    return data

def _auth_token() -> str | None:
    """API token (Zabbix ≥5.4) preferred; else user.login with the read-only
    service account (older servers). Returns None when unconfigured."""
    if settings.ZABBIX_API_TOKEN:
        return settings.ZABBIX_API_TOKEN
    if settings.ZABBIX_USER and settings.ZABBIX_PASSWORD:
        # "user", not "username": the pre-5.4 field name (still accepted later).
        data = _rpc("user.login", {"user": settings.ZABBIX_USER,
                                   "password": settings.ZABBIX_PASSWORD}, None)
        token = data.get("result", "")
        return token or None
    return None

def collect_zabbix(fetcher=None) -> list[RawEvent]:
    if fetcher is not None:
        problems = fetcher()
    else:
        if not settings.ZABBIX_BASE_URL:
            return []
        auth = _auth_token()
        if not auth:
            return []  # unconfigured — no silent failure, heartbeat shows no runs
        data = _rpc("problem.get", {"output": ["eventid", "name", "severity", "clock", "r_eventid"],
                                    "selectHosts": ["host", "name"],
                                    "sortfield": "eventid", "sortorder": "DESC", "limit": 100}, auth)
        problems = data.get("result", [])
    events = []
    for p in problems:
        # skip resolved (r_eventid set non-zero) — old script used recent:true which re-alerted
        r_ev = p.get("r_eventid")
        if r_ev not in (None, "", "0", 0):
            continue
        hosts = p.get("hosts") or []
        device = hosts[0].get("host", "") if hosts else p.get("host", "")
        clock = p.get("clock")
        try:
            occurred = datetime.fromtimestamp(int(clock), tz=timezone.utc)
        except Exception:
            from ..utils_time import utcnow
            occurred = utcnow()
        events.append(RawEvent(
            source="ZABBIX", etype="problem",
            device=(device or p.get("name", "")).strip(),
            summary=str(p.get("name", ""))[:400],
            severity=_sev_map(p.get("severity", 3)),
            occurred_at=occurred, ref=str(p.get("eventid", "")),
            raw=json.dumps(p)[:2000]))
    return events
