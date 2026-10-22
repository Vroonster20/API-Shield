"""
[Task B07] Integration tests for the gateway routes -- these exercise
the full chain (ban check -> rate limit -> validation -> forward -> log).
Use FastAPI's TestClient; you may need both the gateway app and the
target app running (or mock the target call) depending on your approach.
"""
from unittest.mock import AsyncMock

import httpx
from fastapi.testclient import TestClient

from app.routes import gateway
from main import app


client = TestClient(app)


def test_banned_ip_is_blocked_before_rate_limit_check(monkeypatch):
    rate_limit = AsyncMock()
    monkeypatch.setattr(gateway, "is_banned", lambda ip: True)
    monkeypatch.setattr(gateway, "is_allowed", rate_limit)

    response = client.get("/order")

    assert response.status_code == 403
    rate_limit.assert_not_called()


def test_allowed_request_is_logged_and_forwarded(monkeypatch):
    events = []
    monkeypatch.setattr(gateway, "is_banned", lambda ip: False)
    monkeypatch.setattr(gateway, "is_allowed", lambda ip: True)
    monkeypatch.setattr(
        gateway,
        "log_event",
        lambda *event: events.append(event),
    )
    forward = AsyncMock(return_value=httpx.Response(200, content=b"[]"))
    monkeypatch.setattr(gateway.client, "get", forward)

    response = client.get("/order")

    assert response.status_code == 200
    forward.assert_awaited_once()
    assert events == [("testclient", "/orders", "allowed")]


def test_rate_limited_request_is_logged_and_not_forwarded(monkeypatch):
    events = []
    monkeypatch.setattr(gateway, "is_banned", lambda ip: False)
    monkeypatch.setattr(gateway, "is_allowed", lambda ip: False)
    monkeypatch.setattr(
        gateway,
        "log_event",
        lambda *event: events.append(event),
    )
    forward = AsyncMock()
    monkeypatch.setattr(gateway.client, "get", forward)

    response = client.get("/order")

    assert response.status_code == 429
    forward.assert_not_awaited()
    assert events == [("testclient", "/orders", "blocked", "rate-limited")]
