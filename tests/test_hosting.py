"""Hosting paths: dual-dialect engine, live deck stats, Supabase upload shape."""
import json
import urllib.request

from app.database import make_engine, is_sqlite


class _FakeResp:
    def __init__(self, status=200):
        self.status = status
    def read(self, *a):
        return b'{"Key":"b/k.db"}'
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


def test_engine_factory_sqlite_and_postgres():
    lite = make_engine("sqlite:///:memory:")
    assert is_sqlite("sqlite:///./data/elnoc.db") and not is_sqlite("postgresql://x")
    with lite.begin() as c:
        c.exec_driver_sql("PRAGMA journal_mode=WAL")
    pg = make_engine("postgresql+psycopg://u:p@db.supabase.co:5432/postgres")
    assert pg.url.drivername == "postgresql+psycopg"
    assert pg.url.host == "db.supabase.co"


def test_deck_stats_gated_and_live():
    import uuid
    from fastapi.testclient import TestClient
    from app.database import init_db
    init_db()
    from app.main import app
    c = TestClient(app, follow_redirects=False)
    assert c.get("/api/deck-stats").status_code == 401  # API shape: JSON, not redirect
    uname = "deck" + uuid.uuid4().hex[:8]
    r = c.post("/signup", data={"username": uname, "name": "d",
                                "password": "deckpass-12", "password2": "deckpass-12"})
    assert r.status_code == 303
    c.cookies.set("elnoc_session", r.cookies.get("elnoc_session"))
    r = c.get("/api/deck-stats")
    assert r.status_code == 200
    assert set(r.json()) == {"open", "waiting", "shift", "total"}


def test_migrate_sqlite_to_sqlite_roundtrip(tmp_path):
    """Migration machinery proven without a live server: copy the seeded
    test DB into a fresh file, every table's rows must match."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "migrate_sqlite_to_pg", "tools/migrate_sqlite_to_pg.py")
    mg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mg)
    from app.config import settings
    dst = tmp_path / "copy.db"
    report = mg.migrate(f"sqlite:///{settings.DB_PATH}", f"sqlite:///{dst}")
    assert report, "no tables walked"
    assert all(src_n == dst_n for src_n, dst_n in report.values()), report
    assert report.get("case_tbl", [0, 0])[0] > 0  # non-trivial copy


def test_supabase_upload_shape(monkeypatch, tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "backup_supabase", "tools/backup_supabase.py")
    bs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bs)
    seen = {}

    def fake_urlopen(req, timeout=120):
        seen.update(method=req.get_method(), url=req.full_url,
                    auth=req.get_header("Authorization"),
                    ctype=req.get_header("Content-Type"))
        return _FakeResp()

    f = tmp_path / "x.db"
    f.write_bytes(b"fake-db-bytes")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    dest = bs.upload(str(f), "https://xyz.supabase.co", "svc-key", "elnoc-backups")
    assert seen["method"] == "POST"
    assert seen["url"].startswith("https://xyz.supabase.co/storage/v1/object/elnoc-backups/elnoc-")
    assert seen["auth"] == "Bearer svc-key"
    assert dest.startswith("elnoc-backups/elnoc-")


def test_css_motion_sane():
    css = open("app/static/style.css", encoding="utf-8").read()
    assert css.count("{") == css.count("}"), "unbalanced braces"
    for token in ("@keyframes pagein", "@keyframes rise", "@keyframes flash",
                  "prefers-reduced-motion", ".flash", ".stat .v"):
        assert token in css, token
    js = open("app/static/app.js", encoding="utf-8").read()
    assert "deck-stats" in js and "prefers-reduced-motion" in js
