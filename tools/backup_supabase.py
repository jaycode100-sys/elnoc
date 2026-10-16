"""Off-site backup to Supabase Storage (NFR-10 second location).

One command: takes the nightly SQLite copy, then uploads it to your
Supabase bucket under a timestamped name (never overwrites). Needs:
  SUPABASE_URL=https://xyzcompany.supabase.co
  SUPABASE_SERVICE_KEY=<service_role key — server-side only, never in git>
  SUPABASE_BACKUP_BUCKET=elnoc-backups   (create it once, private)

Stdlib only (urllib). Exits 2 with a plain message when unconfigured.
"""
import os
import sys
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, ".")
from app.config import settings  # noqa: E402
from app.services.backup import backup_db  # noqa: E402


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, getattr(settings, name, default) or default) or ""


def upload(path: str, base: str, key: str, bucket: str) -> str:
    name = f"elnoc-{datetime.now(ZoneInfo('Africa/Lagos')).strftime('%Y%m%d-%H%M')}.db"
    with open(path, "rb") as f:
        data = f.read()
    url = base.rstrip("/") + f"/storage/v1/object/{bucket}/{name}"
    req = urllib.request.Request(
        url, data=data,
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/octet-stream"})
    with urllib.request.urlopen(req, timeout=120) as r:
        r.read()
        if r.status not in (200, 201):
            raise RuntimeError(f"upload failed: HTTP {r.status}")
    return f"{bucket}/{name}"


def main() -> int:
    base = _env("SUPABASE_URL")
    key = _env("SUPABASE_SERVICE_KEY")
    bucket = _env("SUPABASE_BACKUP_BUCKET", "elnoc-backups")
    if not base or not key:
        print("SUPABASE_URL / SUPABASE_SERVICE_KEY not set — see HOSTING.md Tier 1.")
        return 2
    local = backup_db(settings.DB_PATH, settings.BACKUP_DIR)
    print(f"local: {local}")
    try:
        dest = upload(local, base, key, bucket)
    except Exception as e:  # noqa: BLE001 — scheduler must see the reason
        print(f"upload FAILED: {e}")
        return 1
    print(f"off-site: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
