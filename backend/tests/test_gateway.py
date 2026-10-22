"""
Integration tests for the gateway routes -- these exercise
the full chain (ban check -> rate limit -> validation -> forward -> log).
"""
import app.security.ban_manager as ban_manager
from fastapi import testclient
from main import app
from app.db.database import create_tables

client = testclient.TestClient(app)


def test_banned_ip_is_blocked_before_rate_limit_check():
    create_tables()
    ban_manager.ban_ip("127.0.0.1")
    print(ban_manager.is_banned("127.0.0.1"))
    payload = {
        "username": "johnsmith",
        "password": "Super_Secret_Password123!"
    }
    response = client.post("/gateway/login",json=payload)
    print(response.status_code)

    assert response.status_code == 403


def test_rate_limited_request_is_logged():
    pass


def test_valid_request_reaches_target_and_is_logged():
    pass

test_banned_ip_is_blocked_before_rate_limit_check()
