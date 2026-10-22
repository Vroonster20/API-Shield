from fastapi.testclient import TestClient
import pytest

from app.core.config import settings
from app.db import database
from app.logging.logger import log_event
from app.routes import admin as admin_routes
from app.routes.auth import ACTIVE_SESSIONS
from main import app


client = TestClient(app)


@pytest.fixture(autouse=True)
def restore_runtime_settings():
    original_values = {
        key: getattr(settings, key)
        for key in (
            "rate_limit_requests",
            "rate_limit_window_seconds",
            "ban_duration_seconds",
        )
    }
    ACTIVE_SESSIONS.clear()
    yield
    for key, value in original_values.items():
        setattr(settings, key, value)
    ACTIVE_SESSIONS.clear()


def admin_headers():
    response = client.post(
        "/admin/login",
        json={
            "username": settings.admin_username,
            "password": settings.admin_password,
        },
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_admin_endpoints_require_authentication():
    for path in ("/admin/logs", "/admin/bans", "/admin/settings"):
        response = client.get(path)
        assert response.status_code == 401
    assert client.post("/admin/fuzz").status_code == 401


def test_fuzz_endpoint_runs_authenticated_gateway_suite(monkeypatch):
    called_with: list[str] = []
    monkeypatch.setattr(settings, "gateway_base_url", "http://gateway.internal:9000")

    async def fake_fuzz_suite(base_url: str):
        called_with.append(base_url)
        return [
            {
                "name": "health_check_control",
                "expected": 200,
                "actual": 200,
                "passed": True,
            }
        ]

    monkeypatch.setattr(admin_routes, "run_fuzz_suite", fake_fuzz_suite)

    response = client.post(
        "/admin/fuzz",
        headers={**admin_headers(), "Host": "untrusted.example"},
    )

    assert response.status_code == 200
    assert response.json()[0]["passed"] is True
    assert called_with == ["http://gateway.internal:9000"]


def test_logs_returns_recent_request_records(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "admin.db"))
    database.create_tables()
    log_event("192.0.2.1", "/login", "blocked", "rate_limit")

    response = client.get("/admin/logs", headers=admin_headers())

    assert response.status_code == 200
    assert response.json()[0]["ip"] == "192.0.2.1"
    assert response.json()[0]["reason"] == "rate_limit"


def test_bans_can_be_created_listed_and_revoked(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "admin.db"))
    monkeypatch.setattr(settings, "ban_duration_seconds", 60)
    database.create_tables()
    headers = admin_headers()

    created = client.post(
        "/admin/bans",
        json={"ip": "192.0.2.10"},
        headers=headers,
    )

    assert created.status_code == 201
    ban = created.json()
    assert ban["ip"] == "192.0.2.10"
    assert ban["status"] == "active"
    assert client.get("/admin/bans", headers=headers).json() == [ban]

    revoked = client.delete(f"/admin/bans/{ban['id']}", headers=headers)

    assert revoked.status_code == 200
    assert client.get("/admin/bans", headers=headers).json() == []
    assert client.delete(f"/admin/bans/{ban['id']}", headers=headers).status_code == 404


def test_ban_rejects_invalid_ip(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "admin.db"))
    database.create_tables()

    response = client.post(
        "/admin/bans",
        json={"ip": "not-an-ip"},
        headers=admin_headers(),
    )

    assert response.status_code == 422


def test_settings_are_read_updated_and_persisted(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "admin.db"))
    database.create_tables()
    headers = admin_headers()
    values = {
        "rate_limit_requests": 20,
        "rate_limit_window_seconds": 90,
        "ban_duration_seconds": 120,
    }

    updated = client.put("/admin/settings", json=values, headers=headers)

    assert updated.status_code == 200
    assert updated.json() == values
    assert client.get("/admin/settings", headers=headers).json() == values
    assert database.get_rules() == {key: str(value) for key, value in values.items()}


def test_settings_reject_non_positive_values(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "admin.db"))
    database.create_tables()

    response = client.put(
        "/admin/settings",
        json={
            "rate_limit_requests": 0,
            "rate_limit_window_seconds": 60,
            "ban_duration_seconds": 120,
        },
        headers=admin_headers(),
    )

    assert response.status_code == 422
