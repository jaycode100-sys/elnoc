"""Intake wiring: unfiltered PRTG poll, RSL parse, Zabbix login fallback,
shared pipeline (incl. FR-82 readings), devices CSV mapping."""
import io
import json
import urllib.request

from app.adapters import prtg, zabbix
from app.adapters.base import RawEvent
from app.adapters.phoenix_csv import import_registry_csv
from app.config import settings
from app.database import SessionLocal
from app.models import Link, OpticalReading, SiteDevice
from app.services.ingestion import ingest_events
from app.utils_time import utcnow


class _FakeResp:
    def __init__(self, doc):
        self._doc = json.dumps(doc).encode()
    def read(self):
        return self._doc
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


def test_parse_rsl():
    assert prtg.parse_rsl("RSL -21.3 dBm, temp ok") == -21.3
    assert prtg.parse_rsl("rx -28dBm") == -28.0
    assert prtg.parse_rsl("all good, no optics here") is None
    assert prtg.parse_rsl(None) is None
    assert prtg.parse_rsl("RSL 9999 dBm") is None  # stray number rejected


def test_prtg_attaches_rsl_to_events():
    evs = prtg.collect_prtg(fetcher=lambda: [
        {"sensor": "RX Level", "device": "D1", "status": "Down", "objid": "1",
         "message": "RSL -29.5 dBm LOW"},
    ])
    assert evs[0].rsl_dbm == -29.5


def test_prtg_poll_has_no_status_filter(monkeypatch):
    """Recoveries only arrive when the poll is unfiltered (FR-08 depends on it)."""
    seen = {}

    def fake_urlopen(url, timeout=30):
        seen["url"] = url
        return _FakeResp({"sensors": [
            {"sensor": "S1", "device": "D1", "status": "Up", "objid": "1",
             "lastup": "12/10/2026 04:09:00 AM"},
        ]})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(settings, "PRTG_BASE_URL", "http://prtg.local")
    monkeypatch.setattr(settings, "PRTG_USERNAME", "u")
    monkeypatch.setattr(settings, "PRTG_PASSHASH", "p")
    evs = prtg.collect_prtg()
    assert "filter_status" not in seen["url"]
    assert [e.etype for e in evs] == ["up"]


def test_zabbix_user_login_fallback(monkeypatch):
    calls = []

    def fake_urlopen(req, timeout=30):
        body = json.loads(req.data.decode())
        calls.append(body["method"])
        if body["method"] == "user.login":
            return _FakeResp({"result": "tok123"})
        return _FakeResp({"result": [
            {"eventid": "9", "name": "Loss high", "severity": "4",
             "clock": "1700000000", "hosts": [{"host": "h1"}], "r_eventid": "0"},
        ]})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(settings, "ZABBIX_BASE_URL", "http://zbx.local")
    monkeypatch.setattr(settings, "ZABBIX_API_TOKEN", "")
    monkeypatch.setattr(settings, "ZABBIX_USER", "svc")
    monkeypatch.setattr(settings, "ZABBIX_PASSWORD", "pw")
    evs = zabbix.collect_zabbix()
    assert calls[0] == "user.login"
    assert len(evs) == 1 and evs[0].device == "h1" and evs[0].severity == "critical"


def test_zabbix_login_uses_pre54_field_name(monkeypatch):
    """5.0's user.login wants {"user"} — {"username"} only exists on 5.4+."""
    seen = {}

    def fake_urlopen(req, timeout=30):
        body = json.loads(req.data.decode())
        if body["method"] == "user.login":
            seen.update(body["params"])
            return _FakeResp({"result": "tok"})
        return _FakeResp({"result": []})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(settings, "ZABBIX_BASE_URL", "http://zbx.local")
    monkeypatch.setattr(settings, "ZABBIX_API_TOKEN", "")
    monkeypatch.setattr(settings, "ZABBIX_USER", "svc")
    monkeypatch.setattr(settings, "ZABBIX_PASSWORD", "pw")
    assert zabbix.collect_zabbix() == []
    assert seen == {"user": "svc", "password": "pw"}


def test_pipeline_stores_optical_reading():
    db = SessionLocal()
    try:
        link = db.query(Link).first()
        re = RawEvent(source="PRTG", etype="down", device=link.name,
                      summary="down with optics", severity="critical",
                      occurred_at=utcnow(), rsl_dbm=-22.5)
        res = ingest_events(db, [re], dry_run=True)
        # an open case may already exist on this link from other tests —
        # either way the event lands on exactly one case:
        assert res["opened"] + res["updated"] == 1
        rows = db.query(OpticalReading).filter(
            OpticalReading.device == link.name,
            OpticalReading.rsl_dbm == -22.5).all()
        assert len(rows) == 1 and rows[0].link_id == link.id
    finally:
        db.close()


def test_devices_csv_maps_sensor_to_link(tmp_path):
    db = SessionLocal()
    try:
        link = db.query(Link).first()
        f = tmp_path / "dev.csv"
        f.write_text("hostname,ip,site,tier,link,monitored_in\n"
                     f"PRTG-HOST-1,10.0.0.9,Ikeja,core,{link.name},PRTG\n")
        n = import_registry_csv(db, "devices", str(f))
        assert n == 1
        d = db.query(SiteDevice).filter(SiteDevice.hostname == "PRTG-HOST-1").first()
        assert d and d.link_id == link.id and d.ip == "10.0.0.9"
    finally:
        db.close()


def test_mailbox_subjects_stay_distinct_but_idempotent():
    """Same sender + same day: different subjects = 2 events; same subject
    twice = 1 (re-poll of UNSEEN mail never duplicates)."""
    from app.adapters import mailbox as mb
    from app.services.correlation import store_event
    db = SessionLocal()
    try:
        mk = lambda subj: mb.collect_mailbox(fetcher=lambda: [
            {"subject": subj, "from": "noc-alerts@example.com",
             "date": "", "body": "link down"}])[0]
        a = mk("Downtime: LTV8 Ikeja")
        b = mk("Downtime: Prec Pearl Main")
        assert a.key_extra and a.key_extra != b.key_extra
        ev1, c1 = store_event(db, a.source, a.etype, a.device, a.summary,
                              a.severity, a.occurred_at, a.ref, a.raw,
                              key_extra=a.key_extra)
        ev2, c2 = store_event(db, b.source, b.etype, b.device, b.summary,
                              b.severity, b.occurred_at, b.ref, b.raw,
                              key_extra=b.key_extra)
        assert (c1, c2) == (True, True) and ev1.key != ev2.key
        _, c3 = store_event(db, a.source, a.etype, a.device, a.summary,
                            a.severity, a.occurred_at, a.ref, a.raw,
                            key_extra=a.key_extra)
        assert c3 is False
    finally:
        db.close()
