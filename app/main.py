"""ELNOC server — one company-controlled FastAPI app + scheduler-separated alerting."""
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from .database import init_db
from .seed import seed_all
from .database import SessionLocal

app = FastAPI(title="ELNOC", version="0.1.0")

BASE = Path(__file__).parent
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")

from .routers import auth, quicklog, cases, dashboard, handover, admin, ingest, acknowledge, playbooks, ask, evidence, links  # noqa: E402
from .security import LoginRequired, get_current_user_optional  # noqa: E402
from .database import get_db  # noqa: E402

app.include_router(auth.router)
app.include_router(quicklog.router)
app.include_router(cases.router)
app.include_router(dashboard.router)
app.include_router(handover.router)
app.include_router(admin.router, prefix="")
app.include_router(ingest.router)
app.include_router(acknowledge.router)
app.include_router(playbooks.router)
app.include_router(ask.router)
app.include_router(evidence.router)
app.include_router(links.router)

@app.on_event("startup")
def _startup():
    from .config import settings as _s
    if _s.SECRET_KEY in ("dev-only-change-me-please-0123456789",
                         "change-me-to-32-random-chars-minimum"):
        print("!!! ELNOC: ELNOC_SECRET_KEY is still the documented default — "
              "sessions can be forged. Set a random value in .env before hosting.")
    init_db()
    db = SessionLocal()
    try:
        seed_all(db)
    finally:
        db.close()

@app.exception_handler(LoginRequired)
async def _login_gate(request, exc: LoginRequired):
    from fastapi.responses import RedirectResponse
    from urllib.parse import quote
    return RedirectResponse(url=f"/login?next={quote(exc.next_url, safe='/')}",
                            status_code=303)

@app.get("/", response_class=None)
def landing(request: Request):
    """Public landing — the default page. Never requires auth, never redirects
    into the app, so it cannot clash with the login gate or the dashboard."""
    from fastapi.templating import Jinja2Templates
    from sqlalchemy import func
    templates = Jinja2Templates(directory=str(BASE / "templates"))
    db = SessionLocal()
    try:
        from .security import check_session
        from .models import AppUser, Case
        token = request.cookies.get("elnoc_session", "")
        username = check_session(token) if token else None
        user = db.query(AppUser).filter(AppUser.username == username).first() if username else None
        stats = {"cases": db.query(func.count()).select_from(Case).scalar() or 0,
                 "open": db.query(func.count()).select_from(Case)
                         .filter(Case.status != "resolved").scalar() or 0}
        return templates.TemplateResponse(request, "landing.html",
            {"user": user, "stats": stats,
             "logged_out": request.query_params.get("logged_out", "")})
    finally:
        db.close()

@app.get("/health")
def health():
    return {"ok": True, "app": "ELNOC"}

LOGO_FILE = BASE.parent / "ELNOC.png"  # single source of truth: root folder

@app.get("/logo.png")
def logo():
    """Solution logo for headers/rails (served from the root ELNOC.png)."""
    from fastapi.responses import FileResponse
    return FileResponse(str(LOGO_FILE), media_type="image/png")

@app.get("/favicon.ico")
def favicon():
    """Browser tab icon — same file, so logo and favicon can never drift."""
    from fastapi.responses import FileResponse
    return FileResponse(str(LOGO_FILE), media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})
