"""SmartOLT adapter tests (FR-03) — real envelope, X-Token, real endpoints."""
from __future__ import annotations
import json
import sys
import types
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.adapters import smartolt  # noqa: E402


class FakeResp:
    def __init__(self, payload, headers=None):
        self._raw = json.dumps(payload).encode()
        self.headers = headers or {}

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _settings(**kw):
    defaults = {"SMARTOLT_BASE_URL": "https://acme.smartolt.com",
                "SMARTOLT_API_KEY": "k", "SMARTOLT_STATUS_SINCE": ""}
    defaults.update(kw)
    return types.SimpleNamespace(**defaults)


def _patch_settings(m):
    orig = smartolt.settings
    smartolt.settings = _settings(**m)
    return orig


def test_unconfigured_returns_nothing(monkeypatch):
    monkeypatch.setattr(smartolt, "settings",
                        _settings(SMARTOLT_BASE_URL="", SMARTOLT_API_KEY=""))
    assert smartolt.collect_smartolt() == []


def test_uses_x_token_header_and_tenant_base(monkeypatch):
    orig = _patch_settings({})
    calls_box = {}

    def fake(req, timeout=None):
        calls_box["url"] = req.full_url
        calls_box["headers"] = dict(req.headers)
        calls_box["token"] = req.get_header("X-token")
        return FakeResp({"status": True, "response": []})

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    try:
        smartolt.collect_smartolt()
    finally:
        smartolt.settings = orig
    assert calls_box["url"].startswith("https://acme.smartolt.com/api/")
    assert calls_box["token"] == "k"
    # must NOT use Bearer auth
    assert "authorization" not in {k.lower() for k in calls_box["headers"]}


def test_pon_outage_is_critical(monkeypatch):
    orig = _patch_settings({})
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: FakeResp(
        {"status": True, "response": [
            {"olt_id": 53, "olt_name": "Ikeja OLT", "board": 0, "port": 3,
             "probable_cause": "fibre cut", "affected_onus": 12, "id": 9}]}))
    try:
        ev = [e for e in smartolt.collect_smartolt() if e.etype == "pon"]
    finally:
        smartolt.settings = orig
    assert ev, "expected a PON outage event"
    assert ev[0].severity == "critical"
    assert ev[0].source == "SMARTOLT"
    assert "fibre cut" in ev[0].summary
    assert "Ikeja OLT" in ev[0].device


def test_onu_fault_states_mapped_and_online_ignored(monkeypatch):
    orig = _patch_settings({})
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: FakeResp(
        {"status": True, "response": [
            {"unique_external_id": "cust-1", "sn": "ZTEGC1", "status": "LOS"},
            {"unique_external_id": "cust-2", "sn": "ZTEGC2", "status": "Power fail"},
            {"unique_external_id": "cust-3", "sn": "ZTEGC3", "status": "Online"}]}))
    try:
        ev = [e for e in smartolt.collect_smartolt() if e.etype == "onu"]
    finally:
        smartolt.settings = orig
    devs = {e.device: e.severity for e in ev}
    assert devs.get("cust-1") == "critical"
    assert devs.get("cust-2") == "critical"
    assert "cust-3" not in devs, "Online ONUs must not create events"


def test_signal_feeds_rsl_reading(monkeypatch):
    orig = _patch_settings({})
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: FakeResp(
        {"status": True, "response": [
            {"unique_external_id": "cust-9", "sn": "ZTEGC9", "rx_signal": -27.4}]}))
    try:
        ev = [e for e in smartolt.collect_smartolt() if e.etype == "reading"]
    finally:
        smartolt.settings = orig
    assert ev and ev[0].rsl_dbm == -27.4


def test_status_error_envelope_raises(monkeypatch):
    orig = _patch_settings({})
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: FakeResp(
        {"status": False, "error": "no OLT found", "error_code": 101}))
    try:
        try:
            smartolt.list_olts()
            raise AssertionError("expected SmartOltError")
        except smartolt.SmartOltError as e:
            assert "101" in str(e)
    finally:
        smartolt.settings = orig


def test_rate_limit_429_message(monkeypatch):
    orig = _patch_settings({})

    def boom(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests",
                                     {"Retry-After": "37"}, None)
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    try:
        try:
            smartolt.list_olts()
            raise AssertionError("expected SmartOltError")
        except smartolt.SmartOltError as e:
            assert "rate limited" in str(e) and "37" in str(e)
    finally:
        smartolt.settings = orig


def test_injected_fetcher_short_circuits(monkeypatch):
    assert smartolt.collect_smartolt(fetcher=lambda: []) == []


def test_incremental_window_passed(monkeypatch):
    orig = _patch_settings({"SMARTOLT_STATUS_SINCE": "2026-10-18 09:00:00"})
    seen = {}

    def fake(req, timeout=None):
        if "get_onus_statuses" in req.full_url:
            seen["url"] = req.full_url
        return FakeResp({"status": True, "response": []})

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    try:
        smartolt.collect_smartolt()
    finally:
        smartolt.settings = orig
    assert "status_changed_after=2026-10-18+09%3A00%3A00" in seen["url"]