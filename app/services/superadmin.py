"""Permanent superadmin profile.

Stored outside the app directory so it survives uninstall/reinstall and the
/api/admin/clear-data wipe.

No default password is ever used. On first run without ELNOC_SUPERADMIN_PASSWORD,
a random password is generated, printed once to stdout, and stored.
"""
from __future__ import annotations

import hashlib, hmac, json, os, secrets, sys
from pathlib import Path
from datetime import datetime, timezone


def _superadmin_path() -> Path:
    appdata = os.getenv("LOCALAPPDATA") or os.path.expanduser("~")
    d = Path(appdata) / "ELNOC"
    d.mkdir(parents=True, exist_ok=True)
    return d / "superadmin.json"


def _hash_pw(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
    return dk.hex(), salt


def ensure_superadmin() -> dict:
    """Ensure a permanent superadmin exists. Returns {username, password_hash, salt}.

    No default password. On first run without ELNOC_SUPERADMIN_PASSWORD, a
    random password is generated, printed once to stdout, and persisted.
    """
    p = _superadmin_path()
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if data.get("username") and data.get("password_hash"):
                return data
        except Exception:
            pass

    username = "superadmin"
    password = os.getenv("ELNOC_SUPERADMIN_PASSWORD")
    if not password:
        password = secrets.token_urlsafe(24)
        print("\n" + "=" * 70)
        print("SUPERADMIN CREATED — password printed ONCE, not stored in plaintext:")
        print(f"  username: {username}")
        print(f"  password: {password}")
        print("=" * 70 + "\n", file=sys.stderr)
    pw_hash, salt = _hash_pw(password)
    data = {"username": username, "password_hash": pw_hash, "salt": salt,
            "created_at": datetime.now(timezone.utc).isoformat()}
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def verify_superadmin(username: str, password: str) -> bool:
    """Check credentials against the permanent superadmin profile."""
    data = ensure_superadmin()
    if username.lower() != data["username"].lower():
        return False
    pw_hash, _ = _hash_pw(password, data["salt"])
    return hmac.compare_digest(pw_hash, data["password_hash"])


def superadmin_username() -> str:
    return ensure_superadmin()["username"]
