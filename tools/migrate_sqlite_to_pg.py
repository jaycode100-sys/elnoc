"""SQLite -> Postgres (Supabase) data move — HOSTING.md Tier 2.

Copies every mapped table in dependency order (SQLAlchemy gives the order),
then verifies row counts table-by-table and exits nonzero on any mismatch.
FTS index is SQLite-only and intentionally skipped (Postgres reads live rows).

Usage (Supabase pooler URL, port 6543 for the app):
  set DATABASE_URL=postgresql+psycopg://postgres.PROJECT:PASSWORD@aws-0-eu-west-1.pooler.supabase.com:6543/postgres
  py -V:3.14 tools/migrate_sqlite_to_pg.py [--src ./data/elnoc.db] [--dry-run]

The machinery (walk + copy + verify) is pytest-covered sqlite->sqlite in
tests/test_hosting.py; only the live wire needs your Supabase URL.
"""
import argparse
import sys

sys.path.insert(0, ".")


def migrate(src_url: str, dst_url: str, dry_run: bool = False) -> dict:
    from sqlalchemy import create_engine
    from app import models  # noqa: F401  (register mappings)
    from app.database import Base, make_engine

    src = create_engine(src_url, future=True)
    dst = make_engine(dst_url)
    Base.metadata.create_all(bind=dst)
    from sqlalchemy import func, select
    report: dict[str, list[int]] = {}
    with src.connect() as sconn, dst.begin() as dconn:
        for table in Base.metadata.sorted_tables:
            rows = sconn.execute(table.select()).all()
            if not dry_run and rows:
                dconn.execute(table.insert(),
                              [dict(r._mapping) for r in rows])
            dst_n = 0 if dry_run else dconn.execute(
                select(func.count()).select_from(table)).scalar()
            report[table.name] = [len(rows), dst_n]
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="./data/elnoc.db")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    import os
    dst_url = os.getenv("DATABASE_URL", "").strip()
    if not dst_url:
        print("DATABASE_URL not set — nothing to migrate into. See HOSTING.md Tier 2.")
        return 2
    src_url = a.src if "://" in a.src else f"sqlite:///{a.src}"
    report = migrate(src_url, dst_url, dry_run=a.dry_run)
    bad = 0
    for table, (src_n, dst_n) in report.items():
        mark = "ok" if (a.dry_run or src_n == dst_n) else "MISMATCH"
        if mark != "ok":
            bad += 1
        print(f"{mark:8s} {table:20s} src={src_n} dst={dst_n}")
    print("dry run — nothing written." if a.dry_run else
          ("ALL TABLES MATCH." if not bad else f"{bad} TABLE(S) MISMATCHED."))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
