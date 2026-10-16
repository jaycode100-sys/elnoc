"""Weekly team-head report (FR-64): repeats, waiting age, MTTR, wrong-team escalations."""
from __future__ import annotations
from collections import Counter
from sqlalchemy.orm import Session
from ..models import Case, Link, CaseEvent
from ..utils_time import age_minutes
from .update_watch import watch_updates, flag_text

def weekly_report(db: Session) -> dict:
    cases = db.query(Case).all()
    per_link = Counter(c.link_id for c in cases if c.link_id)
    link_names = {l.id: l.name for l in db.query(Link).all()}
    repeats = [{"link": link_names.get(lid, str(lid)), "count": n}
               for lid, n in per_link.most_common(10)]
    waiting = [c for c in cases if c.status == "waiting_other_team"]
    waiting_rows = [{"id": c.id, "link": link_names.get(c.link_id, ""),
                     "waiting_on": c.waiting_on, "age_min": age_minutes(c.opened_at)}
                    for c in sorted(waiting, key=lambda c: c.opened_at)]
    resolved = [c for c in cases if c.time_to_resolve_min]
    mttr = round(sum(c.time_to_resolve_min for c in resolved) / len(resolved), 1) if resolved else None
    wrong_team = [c.id for c in cases if "re-escalat" in (c.escalated_to or "").lower()
                  or "wrong" in (c.escalated_to or "").lower()]
    complete = sum(1 for c in cases if c.root_cause_category and c.fix and c.first_thing_to_check_next_time)
    questioned = []
    for c in cases:
        if c.status == "resolved":
            continue
        evs = db.query(CaseEvent).filter(CaseEvent.case_id == c.id).all()
        w = watch_updates(c.symptom or "", c.opened_at, evs)
        flag = flag_text(w)
        if flag:
            questioned.append({"id": c.id, "link": link_names.get(c.link_id, c.device or ""),
                               "flag": flag, "hours": w["hours"]})
    questioned.sort(key=lambda r: r["hours"], reverse=True)
    by_level = Counter(c.escalation_level or "unset" for c in cases if c.status != "resolved")
    return {"repeats": repeats, "waiting": waiting_rows, "mttr_min": mttr,
            "wrong_team_case_ids": wrong_team,
            "complete_card": f"{complete}/{len(cases)}" if cases else "0/0",
            "total": len(cases), "questioned": questioned,
            "by_level": dict(by_level)}
