from datetime import datetime, timezone

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

def test_demo_data_seeds_examples_once_in_an_empty_database(tmp_path, monkeypatch):
    use_temp_db(tmp_path, monkeypatch)

    assert database.seed_demo_data() is True
    assert database.seed_demo_data() is False

    logs = database.get_recent_logs()
    now = datetime.now(timezone.utc).isoformat()
    active_bans = database.get_active_bans(now)
    assert len(logs) == 5
    assert {row["source"] for row in logs} == {"demo"}
    assert any(row["reason"] == "upstream_timeout" for row in logs)
    assert len(active_bans) == 2
    assert {row["source"] for row in active_bans} == {"demo"}
    assert all(row["ip"].startswith(("192.0.2.", "198.51.100.", "203.0.113.")) for row in logs)

def test_demo_seed_preserves_existing_activity(tmp_path, monkeypatch):
    use_temp_db(tmp_path, monkeypatch)
    database.insert_ban(
        "192.0.2.10",
        "2026-01-01T00:00:00+00:00",
        "2026-01-01T00:05:00+00:00",
    )

    assert database.seed_demo_data() is False
    assert database.get_ban(1)["source"] == "live"
    assert database.get_recent_logs() == []
    assert len(database.get_active_bans("2026-01-01T00:01:00+00:00")) == 1

def test_existing_tables_gain_source_column_with_live_default(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "legacy.db"))
    with database.get_db() as conn:
        conn.execute(
            "CREATE TABLE requests_log (id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, "
            "ip TEXT NOT NULL, path TEXT NOT NULL, decision TEXT NOT NULL, reason TEXT)"
        )
        conn.execute(
            "CREATE TABLE bans (id INTEGER PRIMARY KEY, ip TEXT NOT NULL, "
            "banned_at TEXT NOT NULL, expires_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO requests_log VALUES (1, '2026-01-01', '192.0.2.1', "
            "'/login', 'allowed', NULL)"
        )

    database.create_tables()

    assert database.get_recent_logs()[0]["source"] == "live"










