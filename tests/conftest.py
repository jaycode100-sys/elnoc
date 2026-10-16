"""Shared in-memory-ish test DB (file in temp dir, WAL, FTS5)."""
import os, tempfile
os.environ.setdefault("ELNOC_DB_PATH", os.path.join(tempfile.gettempdir(), "elnoc-test.db"))
import app.config as _cfg
_cfg.settings.DB_PATH = os.path.join(tempfile.gettempdir(), "elnoc-test.db")
from app.database import engine, SessionLocal, init_db  # noqa: E402
from app import models  # noqa: F401,E402
from sqlalchemy import text as _t

def fresh_db():
    # wipe file for isolation per module run
    try:
        engine.dispose()
    except Exception:
        pass
    p = _cfg.settings.DB_PATH
    for suf in ("", "-wal", "-shm"):
        try:
            os.remove(p + suf)
        except FileNotFoundError:
            pass
    from app.database import engine as e2, SessionLocal as S2
    init_db()
    db = S2()
    from app.seed import seed_all
    seed_all(db)
    return db
