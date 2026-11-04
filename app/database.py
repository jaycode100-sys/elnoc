"""SQLite + SQLAlchemy setup: WAL mode, timeout, FTS5 table (NFR-08, NFR-15)."""
from __future__ import annotations
import os, sys
from pathlib import Path
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from .config import settings, _res


class Base(DeclarativeBase):
    pass


def _db_url() -> str:
    # Supabase/any Postgres wins when set (NFR-15 scale path); else local SQLite.
    pg = os.getenv("DATABASE_URL", "").strip()
    if pg:
        return pg
    p = Path(settings.DB_PATH)
    # also try bundled data/ if relative
    if not p.is_absolute():
        p = Path(_res(str(p)))
    p.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{p}"

def is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")

def make_engine(url: str):
    """Engine factory (testable): SQLite gets WAL/timeout/pragmas; Postgres
    gets a plain pooled engine — no SQLite-isms leak across."""
    if is_sqlite(url):
        eng = create_engine(
            url,
            connect_args={"timeout": 30, "check_same_thread": False},
            future=True,
        )

        @event.listens_for(eng, "connect")
        def _set_sqlite_pragmas(dbapi_conn, conn_record):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL;")
            cur.execute("PRAGMA synchronous=NORMAL;")
            cur.execute("PRAGMA busy_timeout=30000;")
            cur.execute("PRAGMA foreign_keys=ON;")
            cur.close()

        return eng
    return create_engine(
        # prepare_threshold=None: psycopg's server-side prepared statements
        # die on transaction poolers (Supabase Supavisor 6543) with
        # DuplicatePreparedStatement. Disabling costs ~nothing at NOC scale.
        url, pool_pre_ping=True, future=True,
        connect_args={"prepare_threshold": None})


engine = make_engine(_db_url())

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS case_fts USING fts5(
  case_id UNINDEXED, symptom, fix, root_cause_detail, customer_name, link_name
);
"""

def init_db() -> None:
    from . import models  # noqa: F401  (register tables)
    Base.metadata.create_all(bind=engine)
    if is_sqlite(engine.url.render_as_string(hide_password=True)):
        with engine.begin() as conn:
            conn.execute(text(FTS_SQL))
    # else: Postgres uses ILIKE fallback in similar.py (no FTS5 there)
    ensure_columns()

def ensure_columns() -> None:
    """Lightweight migrations for DBs created before a field existed
    (create_all never alters existing tables). Additive only, idempotent.
    SQLite-only for now; Postgres gets Alembic-style scripts at migration."""
    if not is_sqlite(engine.url.render_as_string(hide_password=True)):
        return
    with engine.begin() as conn:
        cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(case_tbl)")]
        if "escalation_level" not in cols:
            conn.exec_driver_sql(
                "ALTER TABLE case_tbl ADD COLUMN escalation_level VARCHAR(20) DEFAULT ''")
        for name, ddl in (("phoenix_ticket_opened_at", "TIMESTAMP"),
                          ("restored_at", "TIMESTAMP"),
                          ("resolution_challenged_at", "TIMESTAMP"),
                          ("last_contact_attempt_at", "TIMESTAMP"),
                          ("outage_start", "TIMESTAMP")):
            if name not in cols:
                conn.exec_driver_sql(
                    f"ALTER TABLE case_tbl ADD COLUMN {name} {ddl}")
        acols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(attachment)")]
        for name, ddl in (("thread_seq", "INTEGER DEFAULT 1"),
                          ("reply_to_id", "INTEGER"),
                          ("evidence_kind", "VARCHAR(30) DEFAULT 'other'"),
                          ("is_resolution_evidence", "INTEGER DEFAULT 0")):
            if name not in acols:
                conn.exec_driver_sql(
                    f"ALTER TABLE attachment ADD COLUMN {name} {ddl}")
        # ShiftNote new columns (source, case_id, updated_at)
        sncols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(shift_note)")]
        for name, ddl in (("source", "VARCHAR(20) DEFAULT 'manual'"),
                          ("case_id", "INTEGER"),
                          ("updated_at", "TIMESTAMP")):
            if name not in sncols:
                conn.exec_driver_sql(
                    f"ALTER TABLE shift_note ADD COLUMN {name} {ddl}")
        # Create shift_close table if not exists
        conn.exec_driver_sql("""
        CREATE TABLE IF NOT EXISTS shift_close (
            id INTEGER PRIMARY KEY,
            engineer VARCHAR(200) DEFAULT '',
            shift_date VARCHAR(20) DEFAULT '',
            shift VARCHAR(20) DEFAULT 'day',
            power_report_id INTEGER,
            nothing_to_report INTEGER DEFAULT 0,
            override_reason TEXT,
            closed_at TIMESTAMP
        )
        """)
        # Create shift_roster table if not exists
        conn.exec_driver_sql("""
        CREATE TABLE IF NOT EXISTS shift_roster (
            id INTEGER PRIMARY KEY,
            engineer VARCHAR(200) DEFAULT '',
            shift_date VARCHAR(20) DEFAULT '',
            shift VARCHAR(20) DEFAULT 'day',
            created_at TIMESTAMP
        )
        """)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
