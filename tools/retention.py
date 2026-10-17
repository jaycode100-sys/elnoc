"""Retention: 12 months for handover text (team answer, Oct 2026).

Handovers are operational memory, not permanent records. After the window we
drop the stored text/entries but KEEP the handover rows and their case
references — the cases themselves are never deleted (no hard deletes, NFR-09).
Evidence files are left alone; delete them by hand if a policy demands it.

  py -V:3.14 tools/retention.py [--months 12] [--dry-run]
"""
import argparse
import sys
from datetime import timedelta

sys.path.insert(0, ".")
from app.database import init_db, SessionLocal
from app.models import Handover, HandoverImport
from app.utils_time import utcnow


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=12)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    init_db()
    db = SessionLocal()
    cutoff = utcnow() - timedelta(days=30 * a.months)
    try:
        old = db.query(Handover).filter(Handover.created_at < cutoff).all()
        old_imp = db.query(HandoverImport).filter(
            HandoverImport.imported_at < cutoff).all()
        cleared = 0
        for h in old:
            if h.free_notes:
                cleared += 1
            h.free_notes = ""
        for i in old_imp:
            i.raw_text = ""
            i.entries_json = "[]"
        if not a.dry_run:
            db.commit()
        print(f"window: {a.months} months (cutoff {cutoff.date()})")
        print(f"handovers older than window: {len(old)} (free notes cleared on "
              f"{cleared})")
        print(f"pasted imports older than window: {len(old_imp)}")
        print("dry run — nothing written." if a.dry_run else "done.")
        print("Note: case rows, timelines and evidence files are untouched.")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())