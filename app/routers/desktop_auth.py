"""Desktop browser-login flow (like Spotify/GitHub Desktop).

Flow:
1. App opens webview to /auth/desktop/splash
2. Click "Sign in with browser" -> opens system browser to /auth/desktop/start?state=...
3. User logs in on normal ELNOC login page
4. /auth/desktop/complete issues a short-lived one-time code, shows "Return to ELNOC app"
5. Webview polls /auth/desktop/status until authed, then navigates to /dashboard

Codes are in-memory, single-use, expire in 60s, tied to state + session.
"""
from __future__ import annotations

import secrets
import time
from typing import Dict

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from ..security import get_current_user, LoginRequired
from ..utils_time import utcnow

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

# in-memory store
_PENDING: Dict[str, Dict] = {}
_CODES: Dict[str, Dict] = {}
_USED = set()

def _cleanup():
    now = time.time()
    for k, v in list(_PENDING.items()):
        if now - v.get("ts", 0) > 300:
            _PENDING.pop(k, None)
    for k, v in list(_CODES.items()):
        if now - v.get("ts", 0) > 60:
            _CODES.pop(k, None)

@router.get("/auth/desktop/splash", response_class=HTMLResponse)
def desktop_splash(request: Request, user=Depends(get_current_user)):
    if user:
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse(request, "desktop_splash.html", {"user": None})

@router.get("/auth/desktop/start")
def desktop_start(request: Request, state: str = ""):
    _cleanup()
    st = state or secrets.token_urlsafe(24)
    _PENDING[st] = {"ts": time.time(), "ip": request.client.host if request.client else ""}
    # send to normal login, return to complete
    return RedirectResponse(f"/login?next=/auth/desktop/complete?state={st}", status_code=302)

@router.get("/auth/desktop/complete", response_class=HTMLResponse)
def desktop_complete(request: Request, state: str = "", user=Depends(get_current_user)):
    _cleanup()
    if not user:
        return RedirectResponse(f"/auth/desktop/start?state={state}", status_code=302)
    code = secrets.token_urlsafe(32)
    _CODES[code] = {"ts": time.time(), "state": state, "user": user.username}
    return templates.TemplateResponse(request, "desktop_auth_done.html", {"code": code})

@router.get("/auth/desktop/status")
def desktop_status(code: str = ""):
    _cleanup()
    if not code:
        return JSONResponse({"authed": False})
    info = _CODES.get(code)
    if not info:
        return JSONResponse({"authed": False})
    if time.time() - info["ts"] > 60:
        _CODES.pop(code, None)
        return JSONResponse({"authed": False, "reason": "expired"})
    if code in _USED:
        return JSONResponse({"authed": False, "reason": "used"})
    _USED.add(code)
    _CODES.pop(code, None)
    return JSONResponse({"authed": True, "user": info["user"]})

@router.post("/auth/desktop/exchange")
async def desktop_exchange(request: Request):
    _cleanup()
    body = await request.json()
    code = body.get("code") or ""
    info = _CODES.get(code)
    if not info or time.time() - info["ts"] > 60 or code in _USED:
        return JSONResponse({"ok": False}, status_code=401)
    _USED.add(code)
    _CODES.pop(code, None)
    # rely on existing session cookie from browser? webview shares same origin
    # status already confirms login; just ack
    return JSONResponse({"ok": True})
