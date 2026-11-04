"""ELNOC server — one company-controlled FastAPI app + scheduler-separated alerting."""
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from .database import init_db
from .seed import seed_all
from .database import SessionLocal
from .config import settings

app = FastAPI(title="ELNOC", version="0.1.0")

BASE = Path(__file__).parent
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")

from .routers import auth, quicklog, cases, dashboard, handover, admin, ingest, acknowledge, playbooks, ask, evidence, links, assistant, desktop_auth, power, myshift, customers_api, clear_data, reports  # noqa: E402
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
app.include_router(assistant.router)
app.include_router(desktop_auth.router)
app.include_router(power.router)
app.include_router(myshift.router)
app.include_router(customers_api.router)
app.include_router(clear_data.router)
app.include_router(reports.router)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Refuse to start with an insecure SECRET_KEY — sessions can be forged.
    if not settings.SECRET_KEY or len(settings.SECRET_KEY) < 32:
        raise RuntimeError(
            "ELNOC_SECRET_KEY is missing or shorter than 32 characters. "
            "Set a strong random value (e.g. `openssl rand -hex 32`) in .env "
            "before starting the server."
        )
    init_db()
    db = SessionLocal()
    try:
        seed_all(db)
    finally:
        db.close()
    yield


app.router.lifespan_context = lifespan


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


def _logo_candidates():
    """Logo sources, best first: root ELNOC.png, else the bundled app icon.
    In dev, BASE.parent is the repo root; frozen, it's the bundle root (_MEIPASS)."""
    seen = []
    for name in ("ELNOC.png", "ELNOC.ico"):
        p = BASE.parent / name
        if p.exists() and p not in seen:
            seen.append(p)
    return seen


def _logo_response(cache: bool = False):
    from fastapi.responses import FileResponse
    paths = _logo_candidates()
    if not paths:
        from fastapi import Response
        return Response(status_code=404)
    path = paths[0]
    media = "image/png" if path.suffix.lower() == ".png" else "image/x-icon"
    headers = {"Cache-Control": "public, max-age=86400"} if cache else {}
    return FileResponse(str(path), media_type=media, headers=headers)


@app.get("/logo.png")
def logo():
    """Solution logo for headers/rails (served from the root ELNOC.png)."""
    return _logo_response()


@app.get("/favicon.ico")
def favicon():
    """Browser tab icon — same file, so logo and favicon can never drift."""
    return _logo_response(cache=True)
