"""Update-staleness watcher: question an update unchanged 12h+, repeat at 48h+.

The UPDATE line is the shift's promise of motion. When its normalized text
stops changing — same words day after day — ELNOC questions it instead of
copy-pasting it forward. Thresholds live in config (.env-overridable).
"""
from __future__ import annotations
import re
from ..config import settings
from ..utils_time import ensure_utc, utcnow

QUESTION_AT_H = getattr(settings, "STALE_UPDATE_HOURS", 12)
REPEAT_AT_H = getattr(settings, "REPEAT_UPDATE_HOURS", 48)


def normalize_update(text: str) -> str:
    t = (text or "").upper()
    t = re.sub(r"\s+", " ", t).strip().strip(".")
    return t


def watch_updates(symptom: str, opened_at, events: list, now=None) -> dict:
    """events: CaseEvent-likes with .at/.kind/.text (oldest->newest any order).

    Considers the opening symptom + note-kind entries as "the update story".
    Returns {state: fresh|question|repeat, hours, runs, current}.
    """
    now = now or utcnow()
    now = ensure_utc(now)
    trail: list[tuple[object, str]] = []
    if (symptom or "").strip():
        trail.append((opened_at, symptom))
    for e in sorted(events or [], key=lambda x: ensure_utc(x.at)):
        if (e.kind or "") == "note" and (e.text or "").strip():
            trail.append((e.at, e.text))
    if not trail:
        return {"state": "fresh", "hours": 0, "runs": 0, "current": ""}
    norms = [(at, normalize_update(t)) for at, t in trail]
    current = norms[-1][1]
    run_start = norms[-1][0]
    runs = 1
    for at, n in reversed(norms[:-1]):
        if n == current:
            run_start = at
            runs += 1
        else:
            break
    try:
        hours = max(0.0, (now - ensure_utc(run_start)).total_seconds() / 3600)
    except Exception:
        hours = 0.0
    if hours >= REPEAT_AT_H:
        state = "repeat"
    elif hours >= QUESTION_AT_H:
        state = "question"
    else:
        state = "fresh"
    return {"state": state, "hours": round(hours, 1), "runs": runs, "current": current}


def flag_text(w: dict) -> str:
    if w["state"] == "repeat":
        return f"⚠ SAME UPDATE {w['hours']}H — REPEAT, QUESTION IT"
    if w["state"] == "question":
        return f"⚠ SAME UPDATE {w['hours']}H — QUESTION IT"
    return ""
