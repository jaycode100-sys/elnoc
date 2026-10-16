"""Nightly DB copy to second location (NFR-10)."""
from __future__ import annotations
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

def backup_db(db_path: str, backup_dir: str) -> str:
    src = Path(db_path)
    dst_dir = Path(backup_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(ZoneInfo("Africa/Lagos")).strftime("%Y%m%d-%H%M")
    dst = dst_dir / f"elnoc-{stamp}.db"
    shutil.copy2(src, dst)
    # also SQLite WAL sidecars if present
    for suffix in ("-wal", "-shm"):
        side = Path(str(src) + suffix)
        if side.exists():
            shutil.copy2(side, Path(str(dst) + suffix))
    return str(dst)
