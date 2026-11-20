"""
Integration tests for the gateway routes -- these exercise
the full chain (ban check -> rate limit -> validation -> forward -> log).
"""
from unittest.mock import AsyncMock

import httpx
import secrets
import hmac
import hashlib
from fastapi.testclient import TestClient

from app.routes import gateway
from target import target_main
from main import app


client = TestClient(app)

target_client = TestClient(target_main.app)


def test_banned_ip_is_blocked_before_rate_limit_check(monkeypatch,customer_id:int=579):
    rate_limit = AsyncMock()
    monkeypatch.setattr(gateway, "is_banned", lambda ip: True)
    monkeypatch.setattr(gateway, "is_allowed", rate_limit)
    params = {
        "Customer ID":customer_id
    }

    response = client.get(f"/gateway/orders",params=params)

    assert response.status_code == 403
    rate_limit.assert_not_called()


def test_allowed_request_is_logged_and_forwarded(monkeypatch,customer_id:int=579):
    events = []
    monkeypatch.setattr(gateway, "is_banned", lambda ip: False)
    monkeypatch.setattr(gateway, "is_allowed", lambda ip: True)
    monkeypatch.setattr(
        gateway,
        "log_event",
        lambda *event: events.append(event),
    )
    params = {
            "Customer ID":customer_id
        }
    forward = AsyncMock(return_value=httpx.Response(200, content=b"[]"))
    monkeypatch.setattr(gateway.client, "get", forward)

    response = client.get(f"/gateway/orders",params=params)

    assert response.status_code == 200
    forward.assert_awaited_once()
    assert events == [("testclient", "/orders", "allowed")]


def test_rate_limited_request_is_logged_and_not_forwarded(monkeypatch,customer_id:int=579):
    events = []
    monkeypatch.setattr(gateway, "is_banned", lambda ip: False)
    monkeypatch.setattr(gateway, "is_allowed", lambda ip: False)
    monkeypatch.setattr(
        gateway,
        "log_event",
        lambda *event: events.append(event),
    )
    params = {
            "Customer ID":customer_id
        }
    forward = AsyncMock()
    monkeypatch.setattr(gateway.client, "get", forward)

    response = client.get(f"/gateway/orders",params=params)

    assert response.status_code == 429
    forward.assert_not_awaited()
    assert events == [("testclient", "/orders", "blocked", "rate-limited")]

def test_invalid_gateway_signature(monkeypatch,customer_id = 579):
    invalid_key = secrets.token_hex(32)
    request_body = b""
    signature = hmac.new(bytes.fromhex(invalid_key),request_body,hashlib.sha256).hexdigest()
    params = {
            "Customer ID":customer_id
    }
    headers = {
        "Gateway-Signature": signature
    }
    forward = AsyncMock()
    monkeypatch.setattr(target_main.client, "get", forward)
    response = target_client.get(f"/orders",params=params,headers=headers)
    assert response.status_code == 401
    forward.assert_not_awaited()
    #assert "Signature not accepted" in events
