"""Auth gate (FR-60): landing-adjacent login + signup, clean logout.

Routes (no clash by design):
  /            public landing (main.py) — never requires auth
  /login       gate in   (GET shows, POST checks; ?next= preserved)
  /signup      gate in   (GET shows, POST creates engineer + auto-login)
  /logout      gate out  (GET and POST; clears cookie, lands on /?logged_out=1)
  /dashboard…  app pages — unauthenticated page loads redirect to /login?next=…
"""
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path
import re
import os
import time
from collections import defaultdict
from ..database import get_db
from ..models import AppUser
from ..security import (
    verify_password, create_session, hash_password,
    get_current_user_optional, _safe_next,
)
from ..config import settings
from ..services.superadmin import verify_superadmin, ensure_superadmin, superadmin_username

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

COOKIE = "elnoc_session"
USERNAME_RX = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")

# Login rate limiting: max 5 attempts per minute per IP + username
_LOGIN_ATTEMPTS: dict[tuple[str, str], list[float]] = defaultdict(list)
_LOGIN_RATE_LIMIT = 5
_LOGIN_RATE_WINDOW = 60  # seconds


def _check_login_rate(identifier: str) -> bool:
    now = time.time()
    key = ("login", identifier)
    attempts = [t for t in _LOGIN_ATTEMPTS[key] if now - t < _LOGIN_RATE_WINDOW]
    _LOGIN_ATTEMPTS[key] = attempts
    if len(attempts) >= _LOGIN_RATE_LIMIT:
        return False
    attempts.append(now)
    return True


def ensure_superadmin_in_db(db: Session) -> None:
    """Ensure the superadmin user record exists in the DB (role=admin, active).
    clear-data skips superadmin so it survives."""
    su = superadmin_username()
    u = db.query(AppUser).filter(AppUser.username == su).first()
    if not u:
        # Superadmin password is verified against the external profile file,
        # not against this DB row. The row exists only for role/audit purposes.
        h, s = hash_password(superadmin_username())
        db.add(AppUser(username=su, name="Super Admin", role="admin", active=True,
                       password_hash=h, password_salt=s))
        db.commit()
    else:
        u.role = "admin"
        u.active = True
        db.commit()


def _set_session(resp: RedirectResponse, username: str) -> None:
    secure = settings.BASE_URL.startswith("https://")
    resp.set_cookie(COOKIE, create_session(username), httponly=True, samesite="lax",
                    path="/", max_age=settings.SESSION_HOURS * 3600, secure=secure)

def _clear_session(resp: RedirectResponse) -> None:
    # path must match _set_session or the browser keeps the cookie (the "logout
    # doesn't work" class of bug).
    resp.delete_cookie(COOKIE, path="/")

@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/dashboard", signedup: str = "",
               db: Session = Depends(get_db)):
    user = get_current_user_optional(request, db)
    if user:
        return RedirectResponse(url=_safe_next(next), status_code=303)
    return templates.TemplateResponse(request, "login.html",
        {"next": _safe_next(next), "signedup": signedup})

@router.post("/login")
def login(request: Request, username: str = Form(""), password: str = Form(""),
          next: str = Form("/dashboard"), db: Session = Depends(get_db)):
    # Rate limit: 5 attempts per minute per client host + username
    client_host = request.client.host if request.client else "unknown"
    if not _check_login_rate(f"{client_host}:{username.strip().lower()}"):
        return templates.TemplateResponse(request, "login.html",
            {"next": _safe_next(next), "error": "Too many login attempts. Try again later."},
            status_code=429)
    # 1. Permanent superadmin (survives uninstall + clear-data)
    if verify_superadmin(username.strip(), password):
        ensure_superadmin_in_db(db)
        resp = RedirectResponse(url=_safe_next(next), status_code=303)
        _set_session(resp, "superadmin")
        return resp
    # 2. Normal user
    u = db.query(AppUser).filter(AppUser.username == username.strip()).first()
    if not u or not u.active or not verify_password(password, u.password_salt, u.password_hash):
        return templates.TemplateResponse(request, "login.html",
            {"next": _safe_next(next), "error": "Wrong username or password."},
            status_code=401)
    resp = RedirectResponse(url=_safe_next(next), status_code=303)
    _set_session(resp, u.username)
    return resp

@router.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request, next: str = "/dashboard",
                db: Session = Depends(get_db)):
    user = get_current_user_optional(request, db)
    if user:
        return RedirectResponse(url=_safe_next(next), status_code=303)
    # Signup is restricted: either invite-only (no open signup) or limited to
    # the configured email domain. When ADMIN_EMAIL_DOMAINS is not set and no
    # invites exist, signup is closed entirely.
    allowed_domains = [d.strip() for d in os.getenv("ADMIN_EMAIL_DOMAINS", "").split(",") if d.strip()]
    return templates.TemplateResponse(request, "signup.html", {
        "next": _safe_next(next),
        "allowed_domains": allowed_domains,
        "signup_open": bool(allowed_domains),
    })

@router.post("/signup")
def signup(request: Request, username: str = Form(""), name: str = Form(""),
           password: str = Form(""), password2: str = Form(""),
           email: str = Form(""),
           next: str = Form("/dashboard"), db: Session = Depends(get_db)):
    username = username.strip().lower()
    error = None

    # Signup restriction: only allowed email domains (invite-only by default)
    allowed_domains = [d.strip().lower() for d in os.getenv("ADMIN_EMAIL_DOMAINS", "").split(",") if d.strip()]
    if allowed_domains:
        domain = email.split("@")[-1].lower() if "@" in email else ""
        if domain not in allowed_domains:
            error = f"Signup restricted to email domains: {', '.join(allowed_domains)}"
    else:
        error = "Signup is closed. Contact an admin to create an account."

    if not error and not USERNAME_RX.match(username):
        error = "Username: 3–32 chars, letters/numbers/._- only."
    elif not error and len(password) < 8:
        error = "Password: at least 8 characters."
    elif not error and password != password2:
        error = "Passwords do not match."
    elif not error and db.query(AppUser).filter(AppUser.username == username).first():
        error = "That username is taken — try another, or log in."
    if error:
        return templates.TemplateResponse(request, "signup.html",
            {"next": _safe_next(next), "error": error,
             "username": username, "name": name, "email": email},
            status_code=400)
    h, s = hash_password(password)
    db.add(AppUser(username=username, name=name.strip() or username,
                   role="engineer", active=True, password_hash=h, password_salt=s))
    db.commit()
    resp = RedirectResponse(url=_safe_next(next), status_code=303)
    _set_session(resp, username)
    return resp

@router.get("/logout")
def logout_get():
    resp = RedirectResponse(url="/?logged_out=1", status_code=303)
    _clear_session(resp)
    return resp

@router.post("/logout")
def logout_post():
    resp = RedirectResponse(url="/?logged_out=1", status_code=303)
    _clear_session(resp)
    return resp
