"""Power management (day-duty power log): light, generator, inverter, solar,
power tanks. Agentic entry + responsive dashboard page.

Endpoints:
  GET    /power                      — page (chat + table)
  GET    /api/power                  — list reports (optionally ?date=DD/MM/YYYY)
  POST   /api/power                  — create report (form or JSON)
  POST   /api/power/agent            — agentic: parse natural language, create
  GET    /api/power/summary?date=..  — computed summary for a date
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path

from ..database import get_db
from ..models import PowerReport, AppUser
from ..security import get_current_user
from ..config import settings
from ..routers.assistant import llm as assistant_llm
from ..utils_time import utcnow, to_lagos, ensure_utc
from ..services.shift import (
    lagos_date_iso as _lagos_date_iso,
    lagos_date_display as _lagos_date_display,
    parse_lagos_date,
    shift_label as _shift_label,
    parse_battery_level,
    parse_time,
    infer_activity,
)

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def _lagos_date() -> str:
    return _lagos_date_iso()


def parse_battery_level(text: str) -> str:
    """Return the battery level portion of a raw line, best effort."""
    return shift.parse_battery_level(text)


def parse_time(text: str) -> str:
    """Extract HH:MM AM/PM from a raw text line."""
    return shift.parse_time(text)


def infer_activity(text: str) -> str:
    """Infer a short activity phrase from free text."""
    return shift.infer_activity(text)


# ---------------------------------------------------------------- page

@router.get("/power", response_class=HTMLResponse)
def power_page(request: Request, date: str = "",
               user=Depends(get_current_user), db: Session = Depends(get_db)):
    d = date or _lagos_date()
    reports = db.query(PowerReport)\
        .filter(PowerReport.report_date == d)\
        .order_by(PowerReport.created_at.desc()).all()
    # also list recent dates with reports for the date picker
    dates = [r[0] for r in db.query(PowerReport.report_date)
             .distinct().order_by(PowerReport.report_date.desc()).limit(14).all()]
    return templates.TemplateResponse(request, "power.html", {
        "user": user, "reports": reports, "date": d, "dates": dates,
        "agent_hint": None})


# ---------------------------------------------------------------- API: list

@router.get("/api/power")
def api_list_power(date: str = "", limit: int = 100,
                   user=Depends(get_current_user), db: Session = Depends(get_db)):
    d = date or _lagos_date()
    q = db.query(PowerReport).filter(PowerReport.report_date == d)
    reports = q.order_by(PowerReport.created_at.desc()).limit(limit).all()
    return JSONResponse([{
        "id": r.id, "activity": r.activity, "event_time": r.event_time,
        "battery_level": r.battery_level, "source": r.source,
        "summary": r.summary, "created_by": r.created_by,
        "created_at": r.created_at.isoformat(), "raw_text": r.raw_text
    } for r in reports])


# ---------------------------------------------------------------- API: create (manual)

@router.post("/api/power")
def api_create_power(payload: dict, user=Depends(get_current_user),
                     db: Session = Depends(get_db)):
    activity = (payload.get("activity") or "").strip()
    event_time = (payload.get("event_time") or "").strip()
    battery_level = (payload.get("battery_level") or "").strip()
    source = (payload.get("source") or "manual").strip()
    report_date = (payload.get("report_date") or _lagos_date()).strip()
    raw_text = (payload.get("raw_text") or "").strip() or activity
    if not activity:
        return JSONResponse({"error": "activity required"}, status_code=400)
    r = PowerReport(report_date=report_date, activity=activity, event_time=event_time,
                    battery_level=battery_level, source=source, raw_text=raw_text,
                    created_by=user.username)
    db.add(r); db.commit(); db.refresh(r)
    return JSONResponse({"id": r.id, "activity": r.activity, "event_time": r.event_time,
                         "battery_level": r.battery_level, "source": r.source,
                         "summary": r.summary, "created_by": r.created_by,
                         "created_at": r.created_at.isoformat()})


# ---------------------------------------------------------------- API: agentic entry

AGENT_POWER_SYSTEM = """You are ELNOC's power-log agent. Parse the user's natural-language
power report into structured fields. Output ONLY valid JSON, never markdown fences.

Fields:
  activity:    short activity phrase (e.g. "Generator switched OFF", "Inverter battery switched ON")
  event_time:  HH:MM AM/PM if a time is mentioned, else ""
  battery_level: battery percentages as written (e.g. "71%", "Inverter: 24%, Kitchen: 44%, Office: 39%"), else ""
  source:      "agent"
  summary:     one-line summary of what happened

Available power sources: light, big generator, small generator, inverter, solar, power tank.
If the user mentions a source not in that list, use the closest match.
Be concise. Do not invent times or percentages not present in the text."""


def _power_agent_decision(messages: list[dict]) -> dict:
    st = assistant_llm.provider_ready()
    if not st["ready"]:
        return {"tool": None, "answer": "No AI provider configured — enter the report manually using the form above."}
    try:
        raw = assistant_llm.ask_openai(AGENT_POWER_SYSTEM, messages, model=st.get("model", ""), timeout=60)
    except assistant_llm.LLMError:
        try:
            raw = assistant_llm.ask_anthropic(AGENT_POWER_SYSTEM, messages, model=st.get("model", ""), timeout=60)
        except assistant_llm.LLMError as e:
            return {"tool": None, "answer": f"⚠ Agent could not parse: {e}"}
    text = (raw.text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return __import__("json").loads(text)
    except __import__("json").JSONDecodeError:
        return {"tool": None, "answer": text}


@router.post("/api/power/agent")
def api_power_agent(payload: dict, user=Depends(get_current_user),
                    db: Session = Depends(get_db)):
    raw_text = (payload.get("question") or payload.get("raw_text") or "").strip()
    report_date = (payload.get("report_date") or _lagos_date()).strip()
    if not raw_text:
        return JSONResponse({"error": "nothing to parse"}, status_code=400)

    from ..routers.assistant import llm as assistant_llm
    st = assistant_llm.provider_ready()

    decision = _power_agent_decision([{"role": "user", "content": raw_text}])
    # Offline fallback: no provider configured — parse with regex only
    if not st["ready"]:
        activity = infer_activity(raw_text)
        event_time = parse_time(raw_text)
        battery_level = parse_battery_level(raw_text)
        summary = f"{activity} at {event_time or 'time not stated'} — {battery_level or 'level not stated'}"
    else:
        activity = decision.get("activity") or infer_activity(raw_text)
        event_time = decision.get("event_time") or parse_time(raw_text)
        battery_level = decision.get("battery_level") or parse_battery_level(raw_text)
        summary = decision.get("summary") or f"{activity} at {event_time or 'time not stated'}"

    r = PowerReport(report_date=report_date, activity=activity, event_time=event_time,
                    battery_level=battery_level, source="agent-offline" if not st["ready"] else "agent",
                    raw_text=raw_text, summary=summary, created_by=user.username)
    db.add(r); db.commit(); db.refresh(r)

    return JSONResponse({"id": r.id, "activity": r.activity, "event_time": r.event_time,
                         "battery_level": r.battery_level, "source": r.source,
                         "summary": r.summary, "created_by": r.created_by,
                         "created_at": r.created_at.isoformat(),
                         "offline": not st["ready"], "provider": st.get("provider"),
                         "agent_reasoning": decision if st["ready"] else None})


# ---------------------------------------------------------------- API: summary

@router.get("/api/power/summary")
def api_power_summary(date: str = "",
                      user=Depends(get_current_user), db: Session = Depends(get_db)):
    d = date or _lagos_date()
    reports = db.query(PowerReport).filter(PowerReport.report_date == d)\
        .order_by(PowerReport.created_at.asc()).all()
    if not reports:
        return JSONResponse({"date": d, "count": 0, "summary": "No power reports for this date.",
                             "events": [], "first_event": None, "last_event": None})
    events = [{
        "activity": r.activity, "time": r.event_time, "battery": r.battery_level,
        "source": r.source, "created_by": r.created_by
    } for r in reports]
    first = reports[0]
    last = reports[-1]
    # battery at start / shutdown
    start_batt = first.battery_level or "Not stated"
    shutdown_batt = last.battery_level or "Pending"
    # power interruption: from first OFF-like event to last ON-like event
    off_times = [r.event_time for r in reports if re.search(r"off|down|fail|trip|out", r.activity, re.I)]
    on_times = [r.event_time for r in reports if re.search(r"on|up|restor|back", r.activity, re.I)]
    interruption = "Not stated"
    if off_times and on_times:
        try:
            t0 = datetime.strptime(off_times[0], "%I:%M %p")
            t1 = datetime.strptime(on_times[-1], "%I:%M %p")
            diff = t1 - t0
            total_min = int(diff.total_seconds() / 60)
            hrs, mins = divmod(total_min, 60)
            interruption = f"{hrs} hours {mins} minutes ({off_times[0]} – {on_times[-1]})"
        except Exception:
            interruption = f"from {off_times[0]} to {on_times[-1]}"
    elif off_times:
        interruption = f"from {off_times[0]} (no restoration logged yet)"
    summary_lines = [
        f"Power report for {d}: {len(reports)} event(s) logged.",
        f"First event: {first.activity} at {first.event_time or 'time not stated'} ({start_batt}).",
        f"Last event: {last.activity} at {last.event_time or 'time not stated'} ({shutdown_batt}).",
        f"Power interruption: {interruption}.",
    ]
    return JSONResponse({"date": d, "count": len(reports), "summary": " ".join(summary_lines),
                         "events": events, "first_event": first.activity,
                         "last_event": last.activity, "interruption": interruption})


# ---------------------------------------------------------------- API: power trends chart (P3-3)

@router.get("/api/power/trends")
def api_power_trends(days: int = 7, user=Depends(get_current_user),
                     db: Session = Depends(get_db)):
    """P3-3: Power trends for charting — daily event counts and battery levels
    over the last N days (default 7). Returns data suitable for a line/bar chart."""
    from sqlalchemy import func
    end_date = lagos_date_iso()
    # Build list of dates going back `days` days
    from datetime import timedelta
    dates = []
    d0 = to_lagos(utcnow()).date()
    for i in range(days - 1, -1, -1):
        dt = d0 - timedelta(days=i)
        dates.append(dt.isoformat())

    reports = db.query(PowerReport).filter(
        PowerReport.report_date.in_(dates)
    ).order_by(PowerReport.report_date.asc(), PowerReport.created_at.asc()).all()

    # Aggregate per date
    per_date = {d: {"count": 0, "events": [], "battery_levels": []} for d in dates}
    for r in reports:
        rd = r.report_date
        if rd in per_date:
            per_date[rd]["count"] += 1
            per_date[rd]["events"].append({
                "time": r.event_time,
                "activity": r.activity,
                "battery": r.battery_level,
                "source": r.source,
            })
            # Extract numeric battery %
            import re as _re
            m = _re.search(r"(\d{1,3})%", r.battery_level or "")
            if m:
                per_date[rd]["battery_levels"].append(int(m.group(1)))

    series = []
    for d in dates:
        pd = per_date[d]
        avg_batt = None
        if pd["battery_levels"]:
            avg_batt = round(sum(pd["battery_levels"]) / len(pd["battery_levels"]), 1)
        series.append({
            "date": d,
            "display": lagos_date_display(d),
            "event_count": pd["count"],
            "avg_battery": avg_batt,
            "events": pd["events"],
        })

    return JSONResponse({"days": days, "series": series})
