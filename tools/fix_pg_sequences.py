"""One-off: repair Postgres sequences after an explicit-ID migration.

  set DATABASE_URL=postgresql+psycopg://...
  py -V:3.14 tools/fix_pg_sequences.py

Idempotent. Safe to run any time after importing rows with explicit ids.
"""
import os
import sys

sys.path.insert(0, ".")


def main() -> int:
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "migrate_sqlite_to_pg", "tools/migrate_sqlite_to_pg.py")
    mg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mg)
    from app.database import make_engine

    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        print("DATABASE_URL not set.")
        return 2
    eng = make_engine(url)
    n = mg.sync_sequences(eng)
    print(f"sequences synced on {n} table(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())