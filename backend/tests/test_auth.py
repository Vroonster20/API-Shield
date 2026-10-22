"""
Tests for admin auth (login + require_admin).
"""
from unittest.mock import patch

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.config import settings
from app.routes.auth import ACTIVE_SESSIONS, require_admin, router

app = FastAPI()
app.include_router(router, prefix="/admin")


@app.get("/protected")
def protected(session: dict = Depends(require_admin)):
    return {"ok": True}


client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_sessions():
    """Runs before every test so tokens from one test can't leak into another."""
    ACTIVE_SESSIONS.clear()

def get_token() -> str:
    """Log in with the real admin credentials and return the token."""
    response = client.post(
        "/admin/login",
        json={
            "username": settings.admin_username,
            "password": settings.admin_password,
        },
    )
    assert response.status_code == 200
    return response.json()["access_token"]

def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}

# LOGIN tests
def test_login_with_correct_credentials_returns_token():
    response = client.post(
        "/admin/login",
        json={
            "username": settings.admin_username,
            "password": settings.admin_password,
        },
    )

    assert response.status_code == 200

    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["access_token"] in ACTIVE_SESSIONS

def test_login_with_wrong_credentials_returns_401():
    response = client.post(
        "/admin/login",
        json={"username": "bob", "password": "password"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"
    assert len(ACTIVE_SESSIONS) == 0

def test_wrong_username_and_wrong_password_return_identical_responses():
    wrong_username = client.post(
        "/admin/login",
        json={"username": "not-the-admin", "password": settings.admin_password},
    )
    wrong_password = client.post(
        "/admin/login",
        json={"username": settings.admin_username, "password": "not-the-password"},
    )

    assert wrong_username.status_code == wrong_password.status_code == 401
    assert wrong_username.json() == wrong_password.json()
    assert len(ACTIVE_SESSIONS) == 0

# require_admin tests
def test_protected_route_without_authorization_header_returns_401():
    response = client.get("/protected")
    assert response.status_code == 401

def test_protected_route_with_garbage_token_returns_401():
    response = client.get("/protected", headers=auth_header("not-a-real-token"))
    assert response.status_code == 401

def test_protected_route_with_valid_token_returns_200():
    token = get_token()

    response = client.get("/protected", headers=auth_header(token))

    assert response.status_code == 200
    assert response.json() == {"ok": True}

# Expiry tests
@patch("app.routes.auth.time.time")
def test_token_is_valid_just_before_expiry(mock_time):
    mock_time.return_value = 1000.0
    token = get_token()
    expires_at = ACTIVE_SESSIONS[token]["expires_at"]

    mock_time.return_value = expires_at - 1
    response = client.get("/protected", headers=auth_header(token))

    assert response.status_code == 200

@patch("app.routes.auth.time.time")
def test_expired_token_returns_401(mock_time):
    mock_time.return_value = 1000.0
    token = get_token()
    expires_at = ACTIVE_SESSIONS[token]["expires_at"]

    mock_time.return_value = expires_at + 1
    response = client.get("/protected", headers=auth_header(token))

    assert response.status_code == 401

@patch("app.routes.auth.time.time")
def test_expired_token_is_removed_from_active_sessions(mock_time):
    mock_time.return_value = 1000.0
    token = get_token()
    expires_at = ACTIVE_SESSIONS[token]["expires_at"]

    mock_time.return_value = expires_at + 1
    client.get("/protected", headers=auth_header(token))

    assert token not in ACTIVE_SESSIONS