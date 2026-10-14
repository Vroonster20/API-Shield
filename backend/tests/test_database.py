from app.core.config import settings
from app.db import database

def use_temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "test.db"))
    database.create_tables()

def test_tables_exist(tmp_path, monkeypatch):
    use_temp_db(tmp_path, monkeypatch)
    with database.get_db() as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    names = {r["name"] for r in rows}
    assert {"requests_log", "bans", "rules"} <= names

def test_ban_active_then_expired(tmp_path, monkeypatch):
    use_temp_db(tmp_path, monkeypatch)
    database.insert_ban("1.2.3.4", "2026-01-01T00:00:00+00:00", "2026-01-01T00:05:00+00:00")
    assert database.get_active_ban("1.2.3.4", "2026-01-01T00:01:00+00:00") is not None
    assert database.get_active_ban("1.2.3.4", "2026-01-01T00:06:00+00:00") is None
    assert database.get_active_ban("9.9.9.9", "2026-01-01T00:01:00+00:00") is None

def test_log_roundtrip(tmp_path, monkeypatch):
    use_temp_db(tmp_path, monkeypatch)
    from app.logging.logger import log_event
    log_event("1.2.3.4", "/login", "blocked", "rate_limit")
    rows = database.get_recent_logs()
    assert len(rows) == 1
    assert rows[0]["reason"] == "rate_limit"











