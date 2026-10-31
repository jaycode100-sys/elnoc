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
from ..services import agent_tools
from ..utils_time import utcnow, ensure_utc
from datetime import timedelta
import json as _json
import re

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
        "status": llm.provider_ready(), "playbooks": db.query(Playbook).count(),
        "thread": None, "case": None, "messages": [],
        "agent_hint": None})


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
        "case": db.get(Case, t.case_id) if t.case_id else None,
        "agent_hint": None})


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


# ---------------------------------------------------------------- agentic pipeline

AGENT_SYSTEM = """You are ELNOC's agentic NOC assistant. You can answer directly, or you can
call one tool per turn to gather facts, then answer. Rules:
- Output ONLY valid JSON, never markdown fences, never prose outside JSON.
- Each turn, pick exactly one of:
  {"tool": null, "answer": "<your final answer to the user>"}
  {"tool": "<tool_name>", "args": {<tool args>}, "reason": "<why you call it>"}
- Available tools (name + args):
  search_playbooks:   {query: string}  — search ELNOC playbook knowledge
  check_link:         {link_name_or_id: string} — look up a fibre link
  interpret_rsl:      {rsl_dbm: number, optic_model?: string} — optical verdict
  create_case:        {symptom: string, link_name: string, severity?: string, link_state?: string}
                      — create a case ONLY if the user explicitly asks to log one
  acknowledge_case:   {case_id: number} — case ack/escalation info
- If the user asks you to log/create/open a case, use create_case. Otherwise do not.
- If you do not know, say so plainly — do not invent ticket numbers, customers, or measurements.
- Be concise. An engineer at 02:00 wants the next three actions.
- You may chain up to 3 tool calls before giving the final answer."""

AGENT_MAX_STEPS = 3


def _agent_step(system: str, messages: list[dict]) -> dict:
    """Ask the model for the next agent decision: tool call or final answer."""
    st = llm.provider_ready()
    if not st["ready"]:
        return {"tool": None, "answer": llm_provider_missing_answer()}
    provider = st["provider"]
    model = st.get("model", "")
    try:
        if provider == "openai":
            raw = llm.ask_openai(system, messages, model=model, timeout=60)
        else:
            raw = llm.ask_anthropic(system, messages, model=model, timeout=60)
    except llm.LLMError as e:
        return {"tool": None, "answer": f"⚠ Agent could not reason: {e}"}
    text = (raw.text or "").strip()
    # strip accidental fences
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return _json.loads(text)
    except _json.JSONDecodeError:
        # Best effort: treat whole text as final answer
        return {"tool": None, "answer": text}


def llm_provider_missing_answer() -> str:
    return ("No AI provider configured. Add OPENAI_API_KEY or ANTHROPIC_API_KEY to .env, "
            "then restart ELNOC. Until then ELNOC answers with offline tools only.")


def _run_agent(q: str, db: Session, user, case_id: Optional[int] = None) -> dict:
    """Agent loop: decide → act → observe → answer, up to AGENT_MAX_STEPS tool turns."""
    st = llm.provider_ready()
    if not st["ready"]:
        return {"answer": llm_provider_missing_answer(), "steps": [],
                "provider": None, "model": None, "offline": True,
                "fallback": _offline_answer(q, db)}

    system = AGENT_SYSTEM + (
        f"\n\nCURRENT CASE (facts from ELNOC — use these, do not invent others):\n"
        f"{agent_tools._case_context(db, db.get(Case, case_id))}" if case_id else ""
    )
    messages = [{"role": "user", "content": q}]
    steps = []
    for _ in range(AGENT_MAX_STEPS + 1):
        decision = _agent_step(system, messages)
        tool_name = decision.get("tool")
        if not tool_name:
            # final answer
            return {"answer": decision.get("answer", ""), "steps": steps,
                    "provider": st["provider"], "model": st.get("model", ""),
                    "offline": False}
        args = decision.get("args", {}) or {}
        reason = decision.get("reason", "")
        fn = agent_tools.TOOL_REGISTRY.get(tool_name)
        if not fn:
            steps.append({"tool": tool_name, "reason": reason,
                          "result": {"error": f"unknown tool {tool_name}"}})
            messages.append({"role": "user",
                             "content": f"Tool {tool_name} is unknown. Available: "
                                        f"{', '.join(agent_tools.TOOL_REGISTRY)}. "
                                        f"Either call a valid tool or give the final answer."})
            continue
        # bind db / current_user for write tools
        import inspect as _inspect
        sig = _inspect.signature(fn)
        call_kwargs = {}
        for name in ("db", "current_user"):
            if name in sig.parameters:
                call_kwargs[name] = db if name == "db" else user.username
        for k, v in args.items():
            if k in sig.parameters:
                call_kwargs[k] = v
        try:
            result = fn(**call_kwargs)
        except TypeError as e:
            result = {"error": f"bad args for {tool_name}: {e}"}
        steps.append({"tool": tool_name, "reason": reason, "args": args, "result": result})
        messages.append({"role": "user",
                         "content": f"Tool result for {tool_name}: {_json.dumps(result)[:1500]}. "
                                    f"Either call another tool (max {AGENT_MAX_STEPS} total) "
                                    f"or give the final answer now."})
    # fell out of loop — answer with what we have
    return {"answer": "I gathered the facts above but ran out of reasoning steps. "
                      "Here is what I found:", "steps": steps,
            "provider": st["provider"], "model": st.get("model", ""), "offline": False}


@router.post("/api/assistant/agent")
def agent_chat(payload: dict, db: Session = Depends(get_db),
               user=Depends(get_current_user)):
    """Agentic chat: the assistant decides which ELNOC tools to call, then answers."""
    q = (payload.get("question") or "").strip()
    tid = payload.get("thread_id")
    case_id = payload.get("case_id")
    if not q:
        return JSONResponse({"error": "empty question"}, status_code=400)

    hit = find_secret(q)
    if hit:
        return JSONResponse(
            {"error": f"Looks like a credential ({hit}). Remove it and ask again."},
            status_code=400)

    thread = db.get(AssistantThread, tid) if tid else None
    if thread and thread.user != user.username:
        return JSONResponse({"error": "that thread is not yours"}, status_code=403)
    if not thread:
        thread = AssistantThread(user=user.username, case_id=case_id, title=q[:120])
        db.add(thread); db.flush()

    out = _run_agent(q, db, user, case_id=thread.case_id or case_id)

    # persist
    db.add(AssistantMessage(thread_id=thread.id, role="user", content=q))
    db.add(AssistantMessage(thread_id=thread.id, role="assistant",
                            content=out["answer"], provider=out.get("provider"),
                            model=out.get("model"), cited_playbooks="; ".join(
                                s["result"].get("summary", "") for s in out["steps"]
                                if isinstance(s.get("result"), dict) and s["result"].get("summary"))))
    used = db.query(AgentLog).filter(
        AgentLog.asked_by == user.username,
        AgentLog.tools_used.like("%llm:%"),
        AgentLog.created_at >= utcnow() - __import__("datetime").timedelta(hours=24)).count()
    db.add(AgentLog(asked_by=user.username, question=q[:1000],
                    tools_used="llm:agent", answer=out["answer"][:2000],
                    sources="agent_tools", confidence="model",
                    created_at=utcnow()))
    db.commit()

    return JSONResponse({"answer": out["answer"], "thread_id": thread.id,
                         "steps": out["steps"],
                         "provider": out.get("provider"), "model": out.get("model"),
                         "offline": out.get("offline", False),
                         "fallback": out.get("fallback"),
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