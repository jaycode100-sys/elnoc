"""14.1 (*): idempotency, correlation, escalation, channel isolation, maintenance, template."""
from datetime import timedelta
from tests.conftest import fresh_db
from app.services.correlation import store_event, correlate_to_case, in_maintenance
from app.services.escalation import acknowledge, due_for_next_step, recipients_for
from app.notify import channels
from app.notify.templates import render_notification
from app.models import Case, Contact, MaintenanceWindow, Link, Notification
from app.utils_time import utcnow
from app.adapters import prtg, zabbix

db = fresh_db()

def test_collector_idempotent():
    ev1, c1 = store_event(db, "PRTG", "down", "dev-x", "Sensor DOWN", "critical", utcnow())
    ev2, c2 = store_event(db, "PRTG", "down", "dev-x", "Sensor DOWN", "critical", utcnow())
    assert c1 is True and c2 is False
    assert ev1.key == ev2.key
    assert db.query(type(ev1)).count() >= 1

def test_correlation_ten_events_one_case():
    link = db.query(Link).first()
    now = utcnow()
    case_ids = set()
    for i in range(10):
        ev, _ = store_event(db, "PRTG", "down", link.name, f"Sensor DOWN {i}", "critical", now)
        # force same link + same window by reusing link id
        ev.link_id = link.id
        case = correlate_to_case(db, ev)
        case_ids.add(case.id)
    assert len(case_ids) == 1, case_ids

def test_recovery_adds_note_never_silent_close():
    link = db.query(Link).first()
    now = utcnow()
    ev, _ = store_event(db, "PRTG", "down", "rec-dev", "down", "critical", now)
    ev.link_id = link.id
    case = correlate_to_case(db, ev)
    assert case.status != "resolved"
    ev2, _ = store_event(db, "PRTG", "up", "rec-dev", "recovery", "info", now + timedelta(minutes=5))
    ev2.link_id = link.id
    case2 = correlate_to_case(db, ev2)
    assert case2.id == case.id
    assert db.get(Case, case.id).status != "resolved"  # human must close (FR-08)

def test_escalation_ack_stops():
    case = Case(status="open", link_state="down", opened_at=utcnow())
    db.add(case); db.commit()
    assert due_for_next_step(case) is True
    acknowledge(db, case, by="tester")
    assert case.acknowledged_at is not None
    assert due_for_next_step(case) is False

def test_channel_isolation_whatsapp_fail():
    orig = channels.send_whatsapp
    channels.send_whatsapp = lambda *a, **k: channels.ChannelResult(False, "boom")
    try:
        r1 = channels.send_email("a@b.c", "s", "b", dry_run=True)
        r2 = channels.send_whatsapp("123", "b", dry_run=False)
        r3 = channels.send_sms("123", "b", dry_run=True)
        assert r1.ok and r3.ok and not r2.ok
    finally:
        channels.send_whatsapp = orig

def test_maintenance_suppresses():
    db.add(MaintenanceWindow(target_type="device", target="maint-dev",
                             start=utcnow() - timedelta(hours=1),
                             end=utcnow() + timedelta(hours=1),
                             reason="planned", created_by="t"))
    db.commit()
    assert in_maintenance(db, "maint-dev", None, utcnow()) is True
    assert in_maintenance(db, "other-dev", None, utcnow()) is False

def test_template_has_timezone_no_credentials():
    case = db.query(Case).first()
    body = render_notification(case, "Sensor down", "LTV8 Ikeja-RC")
    assert "WAT" in body
    assert "password" not in body.lower()
    assert "Acknowledge:" in body

def test_prtg_recovery_emitted_and_zabbix_host_used():
    evs = prtg.collect_prtg(fetcher=lambda: [
        {"sensor": "S1", "device": "D1", "status": "Down", "objid": "1"},
        {"sensor": "S1", "device": "D1", "status": "Up", "objid": "1"},  # gap #2: must exist
    ])
    kinds = sorted(e.etype for e in evs)
    assert kinds == ["down", "up"], kinds
    zevs = zabbix.collect_zabbix(fetcher=lambda: [
        {"eventid": "9", "name": "High loss", "severity": "4", "clock": "1700000000",
         "hosts": [{"host": "real-host"}], "r_eventid": "0"},
        {"eventid": "8", "name": "Old", "severity": "4", "clock": "1700000000",
         "hosts": [{"host": "h"}], "r_eventid": "5"},  # resolved -> skipped (gap #3)
    ])
    assert lenCached(zevs) == 1 and zevs[0].device == "real-host"

def lenCached(x):
    return len(x)
