"""Brand (root ELNOC.png = logo + favicon) and Zabbix error surfacing."""
import json
import urllib.request
from pathlib import Path

import pytest

from app.adapters import zabbix
from app.config import settings


class _FakeResp:
    def __init__(self, doc):
        self._doc = json.dumps(doc).encode()
    def read(self):
        return self._doc
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


def test_logo_and_favicon_serve_root_png():
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app, follow_redirects=False)
    root = Path("ELNOC.png").read_bytes()
    assert root[:8] == b"\x89PNG\r\n\x1a\n"
    for path in ("/logo.png", "/favicon.ico"):
        r = c.get(path)
        assert r.status_code == 200, path
        assert "image/png" in r.headers.get("content-type", "")
        assert r.content == root  # single source of truth, never drifted


def test_public_pages_carry_favicon_and_logo():
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app, follow_redirects=False)
    for path in ("/", "/login", "/signup"):
        r = c.get(path)
        assert r.status_code == 200, path
        assert 'rel="icon"' in r.text and "/favicon.ico" in r.text, path
        assert 'src="/logo.png"' in r.text and "ELNOC logo" in r.text, path


def test_zabbix_api_error_raises(monkeypatch):
    """Wrong token / bad login must hit the collector-status page, not []."""
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda req, timeout=30: _FakeResp(
            {"error": {"code": -32602, "message": "Invalid params.",
                       "data": "Invalid API token."}}))
    monkeypatch.setattr(settings, "ZABBIX_BASE_URL", "http://zbx.local")
    monkeypatch.setattr(settings, "ZABBIX_API_TOKEN", "bad-token")
    with pytest.raises(RuntimeError, match="Invalid API token"):
        zabbix.collect_zabbix()
