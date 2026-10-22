"""B09 admin routes, using a temporary database."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.db import database
from app.logging.logger import log_event
from app.routes import admin, auth
from app.security.ban_manager import is_banned
from app.security import rate_limiter
from main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "shield.db"))
    monkeypatch.setattr(settings, "admin_username", "test_admin")
    monkeypatch.setattr(settings, "admin_password", "test_password")
    monkeypatch.setattr(settings, "rate_limit_requests", 10)
    monkeypatch.setattr(settings, "rate_limit_window_seconds", 60)
    monkeypatch.setattr(settings, "ban_duration_seconds", 300)
    auth.ACTIVE_SESSIONS.clear()
    rate_limiter._counts.clear()
    with TestClient(app) as client:
        yield client
    auth.ACTIVE_SESSIONS.clear()
    rate_limiter._counts.clear()


@pytest.fixture
def logged_in(client):
    response = client.post("/admin/login", json={
        "username": "test_admin", "password": "test_password",
    })
    assert response.status_code == 200
    token = response.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client


def test_admin_requires_login(client):
    routes = [
        ("GET", "/admin/logs"),
        ("GET", "/admin/bans"),
        ("POST", "/admin/bans"),
        ("DELETE", "/admin/bans/1"),
        ("GET", "/admin/settings"),
        ("PUT", "/admin/settings"),
        ("POST", "/admin/fuzz"),
    ]

    for method, path in routes:
        response = client.request(method, path)
        assert response.status_code == 401, f"Missing token: {method} {path}"

        headers = {"Authorization": "Bearer invalid"}
        response = client.request(method, path, headers=headers)
        assert response.status_code == 401, f"Invalid token: {method} {path}"


def test_logs_are_newest_first_and_limited(logged_in):
    log_event("192.0.2.1", "/first", "allowed")
    log_event("192.0.2.1", "/second", "blocked", "banned")
    response = logged_in.get("/admin/logs?limit=1")
    assert response.status_code == 200
    rows = response.json()["logs"]
    assert len(rows) == 1
    assert rows[0]["path"] == "/second"
    assert rows[0]["reason"] == "banned"


def test_bad_log_limit(logged_in):
    for limit in ["0", "501", "abc"]:
        response = logged_in.get("/admin/logs", params={"limit": limit})
        assert response.status_code == 422, f"Accepted invalid limit: {limit}"


def test_create_list_and_revoke_ban(logged_in):
    response = logged_in.post("/admin/bans", json={"ip": "192.0.2.1"})
    assert response.status_code == 201
    assert is_banned("192.0.2.1")
    response = logged_in.get("/admin/bans")
    bans = response.json()["bans"]
    assert len(bans) == 1
    assert bans[0]["ip"] == "192.0.2.1"
    ban_id = bans[0]["id"]
    response = logged_in.delete(f"/admin/bans/{ban_id}")
    assert response.status_code == 204
    assert response.content == b""
    assert not is_banned("192.0.2.1")
    response = logged_in.get("/admin/bans")
    assert response.json() == {"bans": []}
    response = logged_in.delete(f"/admin/bans/{ban_id}")
    assert response.status_code == 404


def test_expired_bans_are_not_listed(logged_in):
    now = datetime.now(timezone.utc)
    banned_at = now - timedelta(minutes=2)
    expires_at = now - timedelta(minutes=1)
    database.insert_ban("192.0.2.1", banned_at.isoformat(), expires_at.isoformat())
    response = logged_in.get("/admin/bans")
    assert response.json() == {"bans": []}


def test_ipv6_ban_is_normalized(logged_in):
    response = logged_in.post("/admin/bans", json={"ip": "2001:0db8::1"})
    assert response.status_code == 201
    assert response.json()["ip"] == "2001:db8::1"


def test_bad_ban_request(logged_in):
    invalid_bodies = [
        {},
        {"ip": "bad"},
        {"ip": "192.0.2.1", "extra": 1},
    ]
    for body in invalid_bodies:
        response = logged_in.post("/admin/bans", json=body)
        assert response.status_code == 422, f"Accepted invalid ban: {body}"
        response = logged_in.get("/admin/bans")
        assert response.json() == {"bans": []}


def test_bad_ban_id(logged_in):
    response = logged_in.delete("/admin/bans/0")
    assert response.status_code == 422


def test_settings_take_effect_and_reload_at_startup(logged_in):
    values = {
        "rate_limit_requests": 2,
        "rate_limit_window_seconds": 30,
        "ban_duration_seconds": 90,
    }
    response = logged_in.put("/admin/settings", json=values)
    assert response.status_code == 200
    assert response.json() == values
    assert rate_limiter.is_allowed("192.0.2.10")
    assert rate_limiter.is_allowed("192.0.2.10")
    assert not rate_limiter.is_allowed("192.0.2.10")
    logged_in.post("/admin/bans", json={"ip": "192.0.2.2"})
    response = logged_in.get("/admin/bans")
    ban = response.json()["bans"][0]
    banned_at = datetime.fromisoformat(ban["banned_at"])
    expires_at = datetime.fromisoformat(ban["expires_at"])
    duration = expires_at - banned_at
    assert duration.total_seconds() == 90

    # Reset the values in memory so startup has to load them from the database.
    settings.rate_limit_requests = 10
    settings.rate_limit_window_seconds = 60
    settings.ban_duration_seconds = 300
    with TestClient(app):
        response = logged_in.get("/admin/settings")
        assert response.json() == values


def test_bad_settings_do_not_change_config(logged_in):
    invalid_changes = [
        ("rate_limit_requests", 0),
        ("rate_limit_requests", True),
        ("rate_limit_requests", "2"),
        ("rate_limit_requests", 1.5),
        ("rate_limit_window_seconds", -1),
        ("ban_duration_seconds", 604801),
        ("admin_password", "changed"),
    ]
    response = logged_in.get("/admin/settings")
    original = response.json()
    assert "admin_password" not in original

    for field, value in invalid_changes:
        body = original.copy()
        body[field] = value
        response = logged_in.put("/admin/settings", json=body)
        assert response.status_code == 422, f"Accepted invalid setting: {body}"
        response = logged_in.get("/admin/settings")
        assert response.json() == original
        assert database.get_rules() == {}


def test_settings_require_all_fields(logged_in):
    response = logged_in.put("/admin/settings", json={})
    assert response.status_code == 422


def test_fuzz_summary(logged_in, monkeypatch):
    results = [
        {"name": "good", "expected": 422, "actual": 422, "passed": True},
        {"name": "bad", "expected": 422, "actual": 500, "passed": False},
    ]

    def fake_run(url):
        assert url == "http://127.0.0.1:8000"
        return results

    monkeypatch.setattr(admin, "run_fuzz_suite", fake_run)
    response = logged_in.post("/admin/fuzz")
    assert response.status_code == 200
    assert response.json() == {"results": results, "passed": 1, "total": 2}
