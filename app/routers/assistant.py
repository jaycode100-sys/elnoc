"""In-app AI assistant (FR-91..FR-95): official provider APIs, per-case history.

Guardrails, in order, before any token is spent:
  1. provider configured?          -> else the offline tools answer instead
  2. daily cap for this engineer   -> else 429-style refusal, counted
  3. secret scrub (find_secret)    -> refuse rather than forward a password
  4. thread + history loaded, case context assembled, playbooks injected
  5. call, store both turns, log to AgentLog with provider/model/token use

The model is never asked to compute optical numbers; those come from code.
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path

from ..database import get_db
from ..models import (AgentLog, AssistantThread, AssistantMessage, Case,
                      CaseEvent, Playbook, Link, Customer, OpticalReading)
from ..security import get_current_user, find_secret
from ..config import settings
from ..services import llm
from ..services import ai_assist as ai
from ..utils_time import utcnow, ensure_utc
from datetime import timedelta

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def _daily_used(db: Session, username: str) -> int:
    since = utcnow() - timedelta(hours=24)
    return db.query(AgentLog).filter(
        AgentLog.asked_by == username,
        AgentLog.tools_used.like("%llm:%"),
        AgentLog.created_at >= since).count()


def _case_context(db: Session, case: Case) -> str:
    """Facts about the case, so the answer is about THIS link, not generic."""
    lines = [f"CASE #{case.id}"]
    link = db.get(Link, case.link_id) if case.link_id else None
    cust = db.get(Customer, case.customer_id) if case.customer_id else None
    if link:
        lines.append(f"LINK: {link.name} (circuit {link.circuit_id or '?'}, "
                     f"{link.a_end} -> {link.b_end}, {link.medium})")
    if cust:
        lines.append(f"CUSTOMER: {cust.name}")
    lines.append(f"STATE: {case.link_state} | STATUS: {case.status} | "
                 f"SEVERITY: {case.severity} | LEVEL: {case.escalation_level}")
    if case.symptom:
        lines.append(f"SYMPTOM: {case.symptom}")
    if case.waiting_on:
        lines.append(f"WAITING ON: {case.waiting_on}")
    evs = db.query(CaseEvent).filter(CaseEvent.case_id == case.id)\
        .order_by(CaseEvent.at.desc()).limit(6).all()
    if evs:
        lines.append("RECENT UPDATES:")
        lines.extend(f"  - {e.kind}: {e.text[:200]}" for e in evs)
    if link:
        rs = db.query(OpticalReading).filter(OpticalReading.link_id == link.id)\
            .order_by(OpticalReading.occurred_at.desc()).limit(5).all()
        if rs:
            lines.append("RECENT OPTICAL READINGS: "
                         + ", ".join(f"{r.rsl_dbm} dBm" for r in rs if r.rsl_dbm is not None))
    # Code decides the optical verdict; the model only repeats it.
    if rs and rs[0].rsl_dbm is not None:
        v = ai.interpret_rsl(rs[0].rsl_dbm)
        lines.append(f"ELNOC COMPUTED VERDICT (do not recalculate): "
                     f"{v['status']}, margin {v['margin_db']} dB to the "
                     f"{v['limits']['fail_dbm']} dBm fail floor. "
                     f"Likely causes: {'; '.join(v['likely_causes'])}")
    return "\n".join(lines)


def _load_history(db: Session, thread: AssistantThread) -> list[dict]:
    msgs = db.query(AssistantMessage).filter(
        AssistantMessage.thread_id == thread.id).order_by(
        AssistantMessage.id.desc()).limit(
        max(2, settings.ASSISTANT_HISTORY_TURNS * 2)).all()
    msgs.reverse()
    return [{"role": m.role, "content": m.content} for m in msgs
            if m.role in ("user", "assistant")]


def _playbook_refs(answer: str, rows: list) -> str:
    """Which playbooks the answer actually names — stored for audit."""
    cited = []
    for p in rows:
        for token in (f"PB-{p.id}", f"#{p.id}", (p.title or "")[:28]):
            if token and token.lower() in answer.lower() and p.title not in cited:
                cited.append(p.title)
    return "; ".join(cited)


@router.get("/assistant", response_class=HTMLResponse)
def assistant_page(request: Request, user=Depends(get_current_user),
                   db: Session = Depends(get_db)):
    threads = db.query(AssistantThread).filter(
        AssistantThread.user == user.username)\
        .order_by(AssistantThread.id.desc()).limit(25).all()
    open_cases = db.query(Case).filter(Case.status != "resolved")\
        .order_by(Case.opened_at.desc()).limit(60).all()
    return templates.TemplateResponse(request, "assistant.html", {
        "user": user, "threads": threads, "open_cases": open_cases,
        "status": llm.provider_ready(), "playbooks": db.query(Playbook).count()})


@router.get("/assistant/{tid:int}", response_class=HTMLResponse)
def assistant_thread(tid: int, request: Request, user=Depends(get_current_user),
                     db: Session = Depends(get_db)):
    t = db.get(AssistantThread, tid)
    if not t:
        return JSONResponse({"error": "no such thread"}, status_code=404)
    return templates.TemplateResponse(request, "assistant.html", {
        "user": user, "threads": db.query(AssistantThread).filter(
            AssistantThread.user == user.username).order_by(
            AssistantThread.id.desc()).limit(25).all(),
        "open_cases": db.query(Case).filter(Case.status != "resolved")\
            .order_by(Case.opened_at.desc()).limit(60).all(),
        "status": llm.provider_ready(), "playbooks": db.query(Playbook).count(),
        "thread": t, "messages": t.messages,
        "case": db.get(Case, t.case_id) if t.case_id else None})


@router.post("/api/assistant/chat")
def chat(payload: dict, db: Session = Depends(get_db), user=Depends(get_current_user)):
    q = (payload.get("question") or "").strip()
    tid = payload.get("thread_id")
    case_id = payload.get("case_id")
    if not q:
        return JSONResponse({"error": "empty question"}, status_code=400)

    # 1. secrets never leave the building
    hit = find_secret(q)
    if hit:
        return JSONResponse(
            {"error": f"Looks like a credential ({hit}). Remove it and ask again."},
            status_code=400)

    # 2. provider configured?
    st = llm.provider_ready()
    if not st["ready"]:
        return JSONResponse({
            "error": st["reason"], "offline": True,
            "fallback": _offline_answer(q, db)}, status_code=200)

    # 3. cap
    used = _daily_used(db, user.username)
    if used >= settings.ASSISTANT_DAILY_CAP:
        return JSONResponse({
            "error": f"Daily assistant limit reached ({used}/{settings.ASSISTANT_DAILY_CAP}). "
                     f"Resets in 24h."}, status_code=429)

    # 4. thread
    thread = db.get(AssistantThread, tid) if tid else None
    if thread and thread.user != user.username:
        return JSONResponse({"error": "that thread is not yours"}, status_code=403)
    if not thread:
        thread = AssistantThread(user=user.username, case_id=case_id,
                                 title=q[:120])
        db.add(thread)
        db.flush()

    case = db.get(Case, thread.case_id) if thread.case_id else None
    rows = db.query(Playbook).all()
    system = llm.build_system_prompt(llm.playbooks_as_context(rows))
    if case:
        system += ("\n\nCURRENT CASE (facts from ELNOC — use these, do not "
                   f"invent others):\n{_case_context(db, case)}")

    messages = _load_history(db, thread) + [{"role": "user", "content": q}]

    # 5. call + store + log
    try:
        reply = llm.ask(system, messages, provider=st["provider"],
                        model=st.get("model", ""))
    except llm.LLMError as e:
        db.add(AgentLog(asked_by=user.username, question=q[:1000],
                        tools_used="llm:error", answer=str(e)[:500],
                        sources=st["provider"], confidence="none",
                        created_at=utcnow()))
        db.commit()
        return JSONResponse({"error": f"{e}", "fallback": _offline_answer(q, db)},
                            status_code=200)

    cited = _playbook_refs(reply.text, rows)
    db.add(AssistantMessage(thread_id=thread.id, role="user", content=q))
    db.add(AssistantMessage(thread_id=thread.id, role="assistant",
                            content=reply.text, provider=reply.provider,
                            model=reply.model, input_tokens=reply.input_tokens,
                            output_tokens=reply.output_tokens,
                            cited_playbooks=cited))
    db.add(AgentLog(asked_by=user.username, question=q[:1000],
                    tools_used=f"llm:{reply.provider}", answer=reply.text[:2000],
                    sources=cited or f"{reply.provider} + ELNOC playbooks",
                    confidence="model", created_at=utcnow()))
    db.commit()
    return JSONResponse({"answer": reply.text, "thread_id": thread.id,
                         "provider": reply.provider, "model": reply.model,
                         "cited": cited,
                         "tokens": {"in": reply.input_tokens,
                                    "out": reply.output_tokens},
                         "used_today": used + 1, "cap": settings.ASSISTANT_DAILY_CAP})


def _offline_answer(q: str, db: Session) -> str:
    """What ELNOC can still do with no provider configured."""
    ql = q.lower()
    if any(w in ql for w in ("dbm", "rsl", "signal")):
        import re
        m = re.search(r"-?\d+(\.\d+)?\s*dbm", q, re.I)
        if m:
            v = float(re.sub(r"[^\d.-]", "", m.group(0)))
            r = ai.interpret_rsl(v)
            return (f"[offline tool] RSL {v} dBm = {r['status']}, margin "
                    f"{r['margin_db']} dB to the {r['limits']['fail_dbm']} dBm "
                    f"fail floor. Likely causes: {'; '.join(r['likely_causes'])}. "
                    f"First checks: {'; '.join(r['first_checks'])}.")
    pbs = db.query(Playbook).all()
    if pbs:
        words = {w.lower() for w in ql.split() if len(w) > 4}
        scored = sorted(pbs, key=lambda p: -sum(
            1 for w in words if w in (p.title + " " + p.trigger_category).lower()))
        top = scored[:3]
        return ("[offline playbooks] Closest matches: "
                + "; ".join(f"{p.title} — {p.steps[:160]}" for p in top))
    return ("[offline] No AI provider configured and no matching playbook. "
            "Set OPENAI_API_KEY or ANTHROPIC_API_KEY in .env to enable answers.")