import hashlib
import hmac
import json
import sqlite3
from contextlib import contextmanager

import bcrypt
import pytest
from fastapi.testclient import TestClient

from target import target_db, target_main


TEST_KEY = "ab" * 32
TEST_PASSWORD = "S04-test-password!"


@pytest.fixture
def login_client(tmp_path, monkeypatch):
    db_path = tmp_path / "target.db"

    @contextmanager
    def temporary_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    monkeypatch.setattr(target_db, "get_target_db", temporary_db)
    monkeypatch.setenv("SHARED_SECRET_KEY", TEST_KEY)

    password_hash = bcrypt.hashpw(
        TEST_PASSWORD.encode("utf-8"),
        bcrypt.gensalt(rounds=4),
    )

    with temporary_db() as conn:
        conn.execute(
            "CREATE TABLE users (username TEXT PRIMARY KEY, password BLOB)"
        )
        conn.execute(
            "INSERT INTO users (username, password) VALUES (?, ?)",
            ("alice", password_hash),
        )

    with TestClient(target_main.app) as client:
        yield client


def post_login(client, payload):
    body = json.dumps(payload).encode("utf-8")
    signature = hmac.new(
        bytes.fromhex(TEST_KEY),
        body,
        hashlib.sha256,
    ).hexdigest()

    return client.post(
        "/login",
        content=body,
        headers={
            "Content-Type": "application/json",
            "Gateway-Signature": signature,
        },
    )


def test_valid_login(login_client, capsys, caplog):
    response = post_login(
        login_client,
        {"username": "alice", "password": TEST_PASSWORD},
    )

    assert response.status_code == 200
    assert response.json() == {
        "access_token": "mock access token",
        "token_type": "bearer",
        "username": "alice",
    }

    captured = capsys.readouterr()
    output = captured.out + captured.err + caplog.text
    assert TEST_PASSWORD not in output
    assert "$2b$" not in output


@pytest.mark.parametrize(
    "payload",
    [
        {"username": "unknown", "password": TEST_PASSWORD},
        {"username": "alice", "password": "wrong-password"},
        {"password": TEST_PASSWORD},
        {"username": "alice"},
        {},
        {"username": None, "password": TEST_PASSWORD},
        {"username": "alice", "password": None},
        {"username": "alice", "password": ""},
        {"username": "alice", "password": 123},
        {"username": "alice", "password": "x" * 73},
        [],
    ],
)
def test_invalid_login(login_client, payload, capsys, caplog):
    response = post_login(login_client, payload)

    assert response.status_code == 401
    assert response.json() == {
        "detail": "incorrect username or password"
    }

    captured = capsys.readouterr()
    output = captured.out + captured.err + caplog.text
    assert TEST_PASSWORD not in output
    assert "wrong-password" not in output
    assert "$2b$" not in output