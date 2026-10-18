"""SmartOLT adapter (FR-03), built against the real API contract.

Verified from https://www.smartolt.com/openapi.json (checked Oct 2026):

  server   : https://<your-subdomain>.smartolt.com
  auth     : X-Token: <api_key>          (NOT Authorization: Bearer)
  envelope : {"status": true, "response": [ ... ]}
             when status is false -> "error" / "error_code"
  rate cap : X-RateLimit-Limit / -Remaining / -Reset headers,
             HTTP 429 + error_code "rate_limit_exceeded" + Retry-After

Endpoints used:
  GET /api/system/get_olts                     -> OLT inventory
  GET /api/system/get_outage_pons/{olt_id}     -> PON outages (critical)
  GET /api/onu/get_onus_statuses?...           -> ONU state; supports
                                                  status_changed_after for
                                                  incremental polling
  GET /api/onu/get_onus_signals?...            -> optical levels (feeds FR-82)

SmartOLT's own guidance: statuses every 5-7 min, signals every 15-30 min, and
never use get_olts as a heartbeat. We honour both.
"""
from __future__ import annotations
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta
from .base import RawEvent
from ..config import settings
from ..utils_time import utcnow

# SmartOLT ONU states that are NOT a fault.
ONLINE_STATES = {"online", "authorized", "enabled", "working", "ok"}
# State -> severity. LOS means no light at all; power fail is the classic
# "customer says outage but it is their PSU".
ONU_STATE_SEVERITY = {
    "los": "critical",
    "loss of signal": "critical",
    "power fail": "critical",
    "power failure": "critical",
    "offline": "critical",
    "dying-gasp": "major",
    "unknown": "major",
}


class SmartOltError(RuntimeError):
    pass


def _flag(value, default: bool = False) -> bool:
    """Env flags arrive as strings; '0'/'false'/'no'/'' must all read as OFF."""
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in ("0", "false", "no", "off", "none")


def _request(path: str, params: dict | None = None, timeout: int = 30) -> dict:
    base = settings.SMARTOLT_BASE_URL.rstrip("/")
    if not base or not settings.SMARTOLT_API_KEY:
        return {}
    url = base + path
    if params:
        clean = {k: v for k, v in params.items() if v not in (None, "")}
        if clean:
            url += "?" + urllib.parse.urlencode(clean)
    req = urllib.request.Request(url, headers={"X-Token": settings.SMARTOLT_API_KEY,
                                               "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        if e.code == 429:
            retry = e.headers.get("Retry-After", "?")
            raise SmartOltError(f"rate limited (HTTP 429), retry after {retry}s") from e
        raise SmartOltError(f"HTTP {e.code} on {path}") from e
    except Exception as e:  # noqa: BLE001
        raise SmartOltError(f"{type(e).__name__}: {e}") from e
    if not isinstance(body, dict):
        return {}
    if body.get("status") is False:
        raise SmartOltError(f"{body.get('error_code', 'error')}: "
                            f"{body.get('error', 'request failed')}")
    return body


def _items(body: dict) -> list[dict]:
    for key in ("response", "data", "items", "results"):
        v = body.get(key)
        if isinstance(v, list):
            return [x for x in v if isinstance(x, dict)]
    return []


def _olt_label(item: dict, olt_names: dict | None = None) -> str:
    """Prefer a human OLT name so link matching (aliases/devices.csv) works."""
    for key in ("olt_name", "olt", "name"):
        val = item.get(key)
        if val:
            return str(val).strip()
    oid = item.get("olt_id")
    if oid and olt_names:
        return olt_names.get(str(oid), str(oid))
    return f"OLT-{oid}" if oid else "OLT"


def list_olts() -> dict:
    body = _request("/api/system/get_olts")
    names = {}
    for o in _items(body):
        if o.get("olt_id") or o.get("id"):
            names[str(o.get("olt_id") or o.get("id"))] = str(
                o.get("name") or o.get("olt_name") or "").strip() or "OLT"
    return names


def collect_smartolt(fetcher=None) -> list[RawEvent]:
    """PON outages + ONU state changes + optical levels, as RawEvents."""
    if fetcher is not None:
        items = fetcher()
        return list(items) if isinstance(items, list) else []

    if not settings.SMARTOLT_BASE_URL or not settings.SMARTOLT_API_KEY:
        return []  # unconfigured -> controlled manual log path (design sec 9.3)

    events: list[RawEvent] = []
    names = list_olts()

    # ---- 1. PON outages: the headline event
    for oid in list(names) or [""]:
        try:
            body = _request(f"/api/system/get_outage_pons/{oid}")
        except SmartOltError:
            continue
        for p in _items(body):
            dev = _olt_label(p, names)
            port = " ".join(str(p.get(k, "")) for k in ("board", "port") if p.get(k))
            cause = p.get("probable_cause") or p.get("cause") or ""
            affected = p.get("affected_onus") or p.get("onus_count") or ""
            events.append(RawEvent(
                source="SMARTOLT", etype="pon",
                device=f"{dev} PON {port}".strip(),
                summary=(f"PON OUTAGE on {dev}"
                         + (f" port {port}" if port else "")
                         + (f" - probable cause: {cause}" if cause else "")
                         + (f" - ~{affected} ONUs affected" if affected else ""))[:400],
                severity="critical", occurred_at=utcnow(),
                ref=str(p.get("id", "") or p.get("pon_id", "")),
                raw=json.dumps(p)[:2000]))

    # ---- 2. ONU state changes (incremental)
    # A full SmartOLT inventory scan returns EVERY currently-offline ONU. On a
    # real estate that is ~1000+ rows and would open ~1000 NOC cases on one
    # poll. Off by default: per-ONU tickets only when SMARTOLT_ONU_ALERTS=1,
    # otherwise fold the fleet into one summary per zone so the NOC sees the
    # shape of the problem without being buried.
    since = settings.SMARTOLT_STATUS_SINCE or ""
    body = _request("/api/onu/get_onus_statuses", {"status_changed_after": since})
    offline = [o for o in _items(body)
               if str(o.get("status", "")).strip().lower() not in ONLINE_STATES
               and str(o.get("status", "")).strip()]
    if _flag(settings.SMARTOLT_ONU_ALERTS, default=False):
        for o in offline:
            state = str(o.get("status", "")).strip().lower()
            dev = (str(o.get("unique_external_id") or o.get("sn") or "")
                   or f"{_olt_label(o, names)} ONU-{o.get('onu', '?')}")
            events.append(RawEvent(
                source="SMARTOLT", etype="onu", device=dev.strip(),
                summary=(f"ONU {state}: {dev}"
                         + (f" (SN {o.get('sn')})" if o.get("sn") else "")
                         + (f" zone {o.get('zone_id')}" if o.get("zone_id") else ""))[:400],
                severity=ONU_STATE_SEVERITY.get(state, "major"),
                occurred_at=utcnow(),
                ref=str(o.get("sn", "")),
                raw=json.dumps(o)[:2000]))
    else:
        # one rolled-up line per zone: how many in each fault state
        by_zone: dict[str, dict[str, int]] = {}
        for o in offline:
            zone = str(o.get("zone_id") or o.get("zone_name") or "unzoned").strip()
            state = str(o.get("status", "")).strip()
            by_zone.setdefault(zone, {})
            by_zone[zone][state] = by_zone[zone].get(state, 0) + 1
        for zone, counts in sorted(by_zone.items()):
            total = sum(counts.values())
            detail = ", ".join(f"{n} {s}" for s, n in
                               sorted(counts.items(), key=lambda kv: -kv[1]))
            worst = ("critical"
                     if any(s.lower() in ("los", "loss of signal", "power fail",
                                          "power failure", "offline")
                            for s in counts) else "major")
            events.append(RawEvent(
                source="SMARTOLT", etype="onu_fleet", device=f"SMARTOLT ZONE {zone}",
                summary=(f"{total} ONU(s) offline in zone {zone} — {detail}"
                         f"{' — set SMARTOLT_ONU_ALERTS=1 for per-ONU tickets'
                          if total else ''}")[:400],
                severity=worst, occurred_at=utcnow(),
                ref=zone, raw=json.dumps(counts)[:600],
                key_extra=f"{zone}:{detail}"))

    # ---- 3. Optical levels -> FR-82 trend history for the risk watcher
    try:
        sig_body = _request("/api/onu/get_onus_signals")
        for o in _items(sig_body):
            rx = o.get("rx_signal") or o.get("rx_signal_dbm")
            if rx in (None, ""):
                continue
            try:
                dbm = float(rx)
            except (TypeError, ValueError):
                continue
            dev = (str(o.get("unique_external_id") or o.get("sn") or "")
                   or f"{_olt_label(o, names)} ONU-{o.get('onu', '?')}")
            events.append(RawEvent(
                source="SMARTOLT", etype="reading", device=dev.strip(),
                summary=f"Optical level {dbm} dBm rx", severity="info",
                occurred_at=utcnow(), ref=str(o.get("sn", "")),
                raw=json.dumps(o)[:600], rsl_dbm=dbm))
    except SmartOltError:
        pass

    cap = settings.SMARTOLT_MAX_EVENTS
    if cap and len(events) > cap:
        # PON outages first (they are the real NOC signal), then severity order
        def rank(e):
            return (0 if e.etype == "pon" else 1,
                    {"critical": 0, "major": 1, "minor": 2}.get(e.severity, 3))
        events.sort(key=rank)
        dropped = len(events) - cap
        events = events[:cap]
        events.append(RawEvent(
            source="SMARTOLT", etype="info", device="SmartOLT collector",
            summary=(f"Output capped at {cap} events; {dropped} more were "
                     f"truncated (raise SMARTOLT_MAX_EVENTS to keep them)"),
            severity="minor", occurred_at=utcnow()))
    return events