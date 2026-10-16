"""Phase 6a Ask panel (FR-70..FR-76, FR-86..FR-90): glossary-first, cited, minimised, logged."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path
from ..database import get_db
from ..models import AgentLog, Case
from ..security import get_current_user, find_secret
from ..services import ai_assist as ai
from ..utils_time import utcnow

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

ALLOWLIST = ["elnoc-glossary", "optic-datasheet", "team-history"]

@router.get("/ask", response_class=HTMLResponse)
def ask_page(request: Request, user=Depends(get_current_user)):
    return templates.TemplateResponse(request, "ask.html", { "user": user})

@router.post("/api/ask")
def api_ask(payload: dict, db: Session = Depends(get_db), user=Depends(get_current_user)):
    q = (payload.get("question") or "").strip()
    if not q:
        return JSONResponse({"error": "empty"}, status_code=400)
    # guardrail: minimise + secret check before any model call (FR-87)
    hit = find_secret(q)
    if hit:
        return JSONResponse({"error": f"Remove credentials ({hit}) before asking."}, status_code=400)
    ql = q.lower()
    tools: list[str] = []
    if "dbm" in ql or "rsl" in ql or "signal" in ql:
        import re
        m = re.search(r"-?\d+(\.\d+)?\s*dBm", q, re.I)
        val = float(m.group(0).lower().replace("dbm", "").strip()) if m else -27.0
        tools.append("rsl_calculator")
        res = ai.interpret_rsl(val, payload.get("optic_model", ""))
        answer = (f"RSL {val} dBm on {res['optic']}: {res['status']} "
                  f"(margin {res['margin_db']} dB to fail floor {res['limits']['fail_dbm']} dBm). "
                  f"First checks: {'; '.join(res['first_checks'])}.")
        sources = "optic-datasheet limits + ELNOC link history"
        conf = "high" if res["status"] in ("OK", "FAIL") else "medium"
    elif any(w in ql for w in ("which links", "how many", "waited longest", "history", "oregun")):
        tools.append("history_readonly_query")
        rows = db.query(Case).order_by(Case.opened_at.desc()).limit(50).all()
        answer = (f"I checked the last {len(rows)} cases (read-only, no customer names sent out). "
                  f"Ask me to break them down by waiting party or link.")
        sources = "team-history (ELNOC cases)"
        conf = "medium"
    else:
        tools.append("glossary")
        g = ai.explain(q)
        answer = f"{g['term']}: {g['definition']}"
        sources = g["source"]
        conf = g.get("confidence", "medium")
    # kill-switch + audit (FR-86, FR-88)
    db.add(AgentLog(asked_by=user.username, question=q[:1000], tools_used=",".join(tools),
                    answer=answer[:2000], sources=sources, confidence=conf,
                    created_at=utcnow()))
    db.commit()
    return JSONResponse({"answer": answer, "tools": tools, "sources": sources,
                         "confidence": conf, "allowlist": ALLOWLIST,
                         "note": "Numbers from code; drafts need your approval. Thumbs up/down welcome."})
