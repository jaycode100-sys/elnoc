"""Auth (per-engineer accounts, FR-60), secret block (FR-62), audit (FR-61). No external deps."""
from __future__ import annotations
import hashlib, hmac, os, re, secrets
from datetime import datetime, timedelta
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session
from .database import get_db
from .models import AppUser, AuditLog
from .config import settings
from .utils_time import utcnow

# ---------- password hashing (stdlib PBKDF2, no stored credentials issue) ----------
def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
    return dk.hex(), salt

def verify_password(password: str, salt: str, expected: str) -> bool:
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
    return hmac.compare_digest(dk.hex(), expected)

# ---------- signed session cookie ----------
def sign_session(username: str, expiry_ts: int) -> str:
    msg = f"{username}.{expiry_ts}".encode()
    sig = hmac.new(settings.SECRET_KEY.encode(), msg, hashlib.sha256).hexdigest()
    return f"{username}.{expiry_ts}.{sig}"

def check_session(token: str) -> str | None:
    try:
        username, exp, sig = token.rsplit(".", 2)
        exp_i = int(exp)
        if exp_i < int(utcnow().timestamp()):
            return None
        good = hmac.new(settings.SECRET_KEY.encode(), f"{username}.{exp}".encode(), hashlib.sha256).hexdigest()
        if hmac.compare_digest(good, sig):
            return username
    except Exception:
        return None
    return None

def create_session(username: str) -> str:
    exp = int((utcnow() + timedelta(hours=settings.SESSION_HOURS)).timestamp())
    return sign_session(username, exp)

class LoginRequired(Exception):
    """Raised for page requests without a session; handled as a real redirect.

    (The old code raised HTTPException(302), which FastAPI renders as a JSON
    body — browsers do NOT follow it, so users saw {"detail":"login"}.)
    """
    def __init__(self, next_url: str = "/dashboard"):
        super().__init__(next_url)
        self.next_url = next_url

def _safe_next(path: str) -> str:
    if not path or not path.startswith("/") or path.startswith("//"):
        return "/dashboard"
    if path in ("/login", "/signup") or path.startswith(("/login?", "/signup?")):
        return "/dashboard"
    return path

def get_current_user(request: Request, db: Session = Depends(get_db)) -> AppUser:
    token = request.cookies.get("elnoc_session", "")
    username = check_session(token) if token else None
    user = None
    if username:
        user = db.query(AppUser).filter(AppUser.username == username, AppUser.active == True).first()  # noqa: E712
    if not user:
        # API callers get JSON 401; page loads get a real redirect to the gate.
        if request.url.path.startswith("/api/"):
            raise HTTPException(status_code=401, detail="login required")
        raise LoginRequired(_safe_next(request.url.path))
    return user

def get_current_user_optional(request: Request, db: Session = Depends(get_db)) -> AppUser | None:
    try:
        return get_current_user(request, db)
    except (HTTPException, LoginRequired):
        return None

def require_role(*roles: str):
    def _check(user: AppUser = Depends(get_current_user)) -> AppUser:
        if user.role not in roles and user.role != "admin":
            raise HTTPException(status_code=403, detail="forbidden")
        return user
    return _check

# ---------- secret block FR-62 ----------
# This is the gate that stops credentials reaching an external provider (AI
# assistant) or a public paste (handover), so it errs toward flagging. A false
# positive costs the engineer one sentence of retyping; a false negative leaks.
SECRET_PATTERNS = [
    (re.compile(r"(?i)\b(password|passwd|pwd|passphrase|pin)\b\s*[:=]\s*\S+"),
     "password assignment"),
    (re.compile(r"(?i)\b(password|passwd|passphrase)\b\s+(?:is|was|=|:)\s*\S+"),
     "password given in words"),
    (re.compile(r"(?i)\bsnmp\b.{0,20}(community|key|string)\s*[:=]\s*\S+"), "SNMP string"),
    (re.compile(r"(?i)\b(api[_-]?key|secret|token)\s*[:=]\s*\S+"), "API key/secret"),
    (re.compile(r"(?i)\b(api[_-]?key|secret|token|passhash|password)\s*[:=]\s*\S+"),
     "API key/secret"),
    # "... token <value>" with no separator — "token bucket" stays clean because
    # the value must be 20+ chars.
    (re.compile(r"(?i)\b(api[_-]?key|secret|token|passhash)\s+[A-Za-z0-9._-]{20,}"),
     "API key/secret in words"),
    (re.compile(r"(?i)[A-Z_]*passhash\s*[:=]\s*[0-9a-f]{16,}"), "PRTG passhash"),
    (re.compile(r"(?i)\b(ssh|winbox|sshpass)\b.{0,30}(password|passwd)\s*[:=]"),
     "device password"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key"),
    # provider key shapes — these are unmistakable
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), "OpenAI-style API key"),
    (re.compile(r"\bsk-ant-[A-Za-z0-9_-]{16,}"), "Anthropic API key"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"), "GitHub token"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key id"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}"),
     "JWT / bearer token"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._-]{20,}"), "bearer token"),
    # our own config values pasted in
    (re.compile(r"(?i)\bpasshash\b\s*[:=]?\s*[0-9a-f]{16,}"), "PRTG passhash"),
    (re.compile(r"(?i)\bsupabase_service_key\b"), "Supabase service key"),
]


def find_secret(text: str) -> str | None:
    if not text:
        return None
    for rx, label in SECRET_PATTERNS:
        if rx.search(text):
            return label
    return None

def audit(db: Session, entity: str, entity_id: str, changed_by: str, diff: str) -> None:
    last = db.query(AuditLog).filter(
        AuditLog.entity == entity, AuditLog.entity_id == str(entity_id)
    ).order_by(AuditLog.version.desc()).first()
    v = (last.version + 1) if last else 1
    db.add(AuditLog(entity=entity, entity_id=str(entity_id), version=v,
                    changed_by=changed_by, changed_at=utcnow(), diff=diff[:4000]))
