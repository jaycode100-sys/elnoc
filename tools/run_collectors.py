"""Scheduler entry: collectors + escalation checks every 5 min (sec 5, NFR-03).
Run separately from the web UI so alerting survives a UI fault.
Windows Task Scheduler / cron / systemd:  python tools/run_collectors.py [--dry-run]

Uses a lock file so overlapping runs cannot hit 'database is locked' (gap #9).
"""
import sys, os
sys.path.insert(0, ".")
from pathlib import Path
from app.database import init_db, SessionLocal
from app.adapters import prtg, zabbix, smartolt, mailbox
from app.services.ingestion import ingest_events
from app.services.heartbeat import record_run
from app.services.escalation import due_for_next_step, steps_for_case
from app.notify.dispatcher import notify_case, retry_failed
from app.models import Case, Link, Customer

LOCK = Path("data/collectors.lock")

def _locked():
    # simple cross-platform lock via exclusive create
    try:
        fd = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, b"run")
        os.close(fd)
        return True
    except FileExistsError:
        print("another collector run is active; skipping")
        return False

def main(dry_run: bool = False):
    init_db()
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    if not _locked():
        return
    try:
        db = SessionLocal()
        for source, fn in [("PRTG", prtg.collect_prtg), ("ZABBIX", zabbix.collect_zabbix),
                           ("SMARTOLT", smartolt.collect_smartolt), ("MAILBOX", mailbox.collect_mailbox)]:
            try:
                events = fn()
                res = ingest_events(db, events, dry_run=dry_run)
                record_run(db, source, True)
                print(f"{source}: {len(events)} events "
                      f"(opened={res['opened']} updated={res['updated']} "
                      f"suppressed={res['suppressed']} notified={res['notified']})")
            except Exception as e:  # noqa: BLE001 — errors surface on status page, never silent (gap #10)
                record_run(db, source, False, str(e)[:500])
                print(f"{source} FAILED: {e}")
        # escalation sweep: advance unacknowledged cases past their wait
        for case in db.query(Case).filter(Case.status != "resolved").all():
            if case.acknowledged_at:
                continue
            if due_for_next_step(case):
                steps = steps_for_case(db, case)
                nxt = case.current_escalation_step  # 0-based index into steps
                if nxt < len(steps):
                    from app.models import Contact
                    c = db.get(Contact, steps[nxt].contact_id)
                    from app.utils_time import utcnow
                    from app.models import CaseEvent
                    db.add(CaseEvent(case_id=case.id, at=utcnow(), engineer="system",
                                     kind="escalation",
                                     text=f"Escalated to step {nxt+1}: {c.name if c else '?'}"))
                    case.current_escalation_step += 1
                    if not dry_run and c:
                        notify_case(db, case, f"Escalation step {nxt+1}",
                                    f"{c.team} {c.name}", dry_run=False,
                                    force_channels=(steps[nxt].channels or "email,whatsapp").split(","))
                    else:
                        from app.utils_time import utcnow as _u
                        case.last_escalation_at = _u()
                    db.commit()
        retry_failed(db, dry_run=dry_run)
        db.close()
    finally:
        try:
            LOCK.unlink()
        except Exception:
            pass

if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv or "--dry" in sys.argv)
