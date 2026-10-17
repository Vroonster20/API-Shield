"""[Task B04] Tests for the ban manager."""
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.db import database
from app.security import ban_manager


@pytest.fixture(autouse=True)
def temporary_database(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "test.db"))
    monkeypatch.setattr(settings, "ban_duration_seconds", 60)
    database.create_tables()


def test_ip_not_default_banned():
    assert ban_manager.is_banned("192.0.2.1") is False


def test_ban_ip_():
    ban_manager.ban_ip("192.0.2.1")

    assert ban_manager.is_banned("192.0.2.1") is True
    assert ban_manager.is_banned("192.0.2.2") is False

    with database.get_db() as conn:
        row = conn.execute(
            "SELECT banned_at, expires_at FROM bans WHERE ip = ?",
            ("192.0.2.1",),
        ).fetchone()
    duration = (
        datetime.fromisoformat(row["expires_at"])
        - datetime.fromisoformat(row["banned_at"])
    )
    assert duration == timedelta(seconds=60)


@pytest.mark.parametrize("elapsed, expected", [(59, True), (60, False), (61, False)])
def test_ban_expires(monkeypatch, elapsed, expected):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(ban_manager, "_utc_now", lambda: start)
    ban_manager.ban_ip("192.0.2.1")
    monkeypatch.setattr(
        ban_manager, "_utc_now", lambda: start + timedelta(seconds=elapsed)
    )
    assert ban_manager.is_banned("192.0.2.1") is expected