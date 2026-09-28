"""Exercise the private management API through actual ASGI requests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest

from shield_api.admin_api import create_management
from shield_api.admin_auth import ABSOLUTE_MS, AuthError, AuthService, IDLE_MS, csrf_matches
from shield_api.contracts import Registry
from shield_api.db import Database, effective_now
from shield_api.settings import Settings


PASSWORD = "a-long-test-password"
ORIGIN = "http://admin.localhost:8081"
DOCUMENT = {
    "schema_version": 1,
    "service": {
        "id": "demo",
        "name": "Demo",
        "public_host": "api.localhost",
        "upstream_id": "origin",
        "enabled": True,
        "unmatched_action": "baseline",
        "max_body_bytes": 1000,
        "ip_rate": {"limit": 100, "window_seconds": 60},
        "routes": [],
    },
}


class NoopFuzz:
    async def startup(self):
        pass

    async def close(self):
        pass

    async def start(self, profile_id, seed, admin_id):
        from shield_api.fuzz_jobs import FuzzBusy

        raise FuzzBusy()

    async def list(self, cursor=None, limit=50):
        return {"items": [], "next_cursor": None}

    async def detail(self, run_id):
        return None


@asynccontextmanager
async def setup(tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        registry_file=tmp_path / "registry.json",
        admin_origin=ORIGIN,
        mode="development",
        rate_secret_file=tmp_path / "rate.key",
    )
    registry = Registry.model_validate(
        {
            "upstreams": [
                {"id": "origin", "name": "Origin", "scheme": "http", "host": "127.0.0.1", "port": 9000}
            ]
        }
    )
    settings.rate_secret_file.write_bytes(b"s" * 32)
    db = Database(settings.db_path, writer_budget_ms=5000)
    await db.initialize()
    await AuthService(db, b"s" * 32).bootstrap_admin("operator", PASSWORD)
    app = create_management(settings, db, registry, NoopFuzz())
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 53421))
        async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as client:
            yield client, db
    await db.close()


async def login(client):
    result = await client.post(
        "/admin/v1/auth/login",
        json={"username": "operator", "password": PASSWORD},
        headers={"Origin": ORIGIN},
    )
    assert result.status_code == 200, result.text
    return result.json()["csrf_token"]


def write_headers(csrf):
    return {"Origin": ORIGIN, "X-CSRF-Token": csrf}


@pytest.mark.asyncio
async def test_auth_guards_cookie_csrf_logout_and_reset(tmp_path):
    async with setup(tmp_path) as (client, db):
        for path in (
            "/admin/v1/auth/session",
            "/admin/v1/registry",
            "/admin/v1/config",
            "/admin/v1/status",
            "/admin/v1/bans",
            "/admin/v1/events",
            "/admin/v1/fuzz-runs",
            "/admin/v1/fuzz-runs/missing",
        ):
            response = await client.get(path)
            assert response.status_code == 401, (path, response.text)
            assert response.headers["Cache-Control"] == "no-store"
        for path, method in (
            ("/admin/v1/config", "PUT"),
            ("/admin/v1/bans", "POST"),
            ("/admin/v1/bans/missing/revoke", "POST"),
            ("/admin/v1/fuzz-runs", "POST"),
            ("/admin/v1/auth/logout", "POST"),
        ):
            response = await client.request(method, path, json={})
            assert response.status_code == 401, (path, response.text)
        assert (
            await client.post("/admin/v1/auth/login", json={"username": "operator", "password": PASSWORD})
        ).status_code == 403
        csrf = await login(client)
        assert "shield_dev_session=" in client.cookies.jar.__str__() or "shield_dev_session" in client.cookies
        assert (await client.get("/admin/v1/auth/session")).json()["csrf_token"] == csrf
        assert (await client.put("/admin/v1/config", json={}, headers={"Origin": ORIGIN})).status_code == 403
        assert (
            await client.put(
                "/admin/v1/config", json={}, headers={"Origin": "http://evil.localhost", "X-CSRF-Token": csrf}
            )
        ).status_code == 403
        assert (
            await client.put("/admin/v1/config", json={}, headers=write_headers("bad"))
        ).status_code == 403
        assert (
            await client.put(
                "/admin/v1/config", json={}, headers={**write_headers(csrf), "X-CSRF-Token": b"\xe9"}
            )
        ).status_code == 403
        assert (
            await client.post("/admin/v1/auth/logout", json={}, headers=write_headers(csrf))
        ).status_code == 204
        assert (await client.get("/admin/v1/auth/session")).status_code == 401
        await login(client)
        await AuthService(db, b"s" * 32).reset_password("operator", "another-long-test-password")
        assert (await client.get("/admin/v1/auth/session")).status_code == 401


@pytest.mark.asyncio
async def test_config_bans_events_and_bounds(tmp_path):
    async with setup(tmp_path) as (client, db):
        csrf = await login(client)
        headers = write_headers(csrf)
        assert (await client.get("/admin/v1/config")).json() == {"version": None, "document": None}
        assert (await client.get("/admin/v1/status")).json()["status"] == "unconfigured"
        assert (await client.get("/admin/v1/registry")).json()["upstreams"][0]["id"] == "origin"
        saved = await client.put(
            "/admin/v1/config", json={"expected_version": None, "document": DOCUMENT}, headers=headers
        )
        assert saved.status_code == 202, saved.text
        assert saved.json() == {"desired_version": 1, "applied_version": None, "status": "pending"}
        assert (await client.get("/admin/v1/config")).json()["version"] == 1
        conflict = await client.put(
            "/admin/v1/config", json={"expected_version": None, "document": DOCUMENT}, headers=headers
        )
        assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "CONFIG_CONFLICT"
        invalid = await client.put(
            "/admin/v1/config", json={"expected_version": 1, "document": {}}, headers=headers
        )
        assert invalid.status_code == 422 and invalid.json()["error"]["code"] == "CONFIG_INVALID"
        assert (await client.get("/admin/v1/config")).json()["version"] == 1
        ban = await client.post(
            "/admin/v1/bans",
            json={"ip": "192.0.2.5", "duration_seconds": 30, "reason": "demo_test"},
            headers=headers,
        )
        assert ban.status_code == 201, ban.text
        ban_id = ban.json()["ban_id"]
        assert "192.0.2.5" not in ban.text
        assert (await client.get("/admin/v1/bans?state=active")).json()["items"][0]["ban_id"] == ban_id
        duplicate = await client.post(
            "/admin/v1/bans",
            json={"ip": "192.0.2.5", "duration_seconds": 30, "reason": "demo_test"},
            headers=headers,
        )
        assert duplicate.status_code == 409
        revoked = await client.post(f"/admin/v1/bans/{ban_id}/revoke", json={}, headers=headers)
        assert revoked.status_code == 200 and revoked.json()["revoked"]
        assert (await client.get("/admin/v1/bans?state=revoked")).json()["items"][0]["ban_id"] == ban_id
        events = await client.get("/admin/v1/events?kind=security")
        assert events.status_code == 200 and events.json()["items"]
        assert "192.0.2.5" not in events.text
        first_page = await client.get("/admin/v1/events?kind=security&limit=1")
        next_cursor = first_page.json()["next_cursor"]
        assert next_cursor
        second_page = await client.get(
            "/admin/v1/events", params={"kind": "security", "cursor": next_cursor, "limit": 1}
        )
        assert second_page.status_code == 200
        assert second_page.json()["items"][0]["id"] != first_page.json()["items"][0]["id"]
        assert (
            await client.get("/admin/v1/events", params={"kind": "request", "cursor": next_cursor})
        ).status_code == 400
        assert (
            await client.get("/admin/v1/events?kind=security&from_ms=1&to_ms=9999999999999")
        ).status_code == 400
        assert (await client.get("/admin/v1/bans?cursor=bad")).status_code == 400
        assert (await client.get("/admin/v1/events?limit=101")).status_code == 400
        async with db.read() as conn:
            assert (await (await conn.execute("SELECT count(*) AS n FROM config_revisions")).fetchone())[
                "n"
            ] == 1


@pytest.mark.asyncio
async def test_ingress_body_limits_and_fuzz_error(tmp_path):
    async with setup(tmp_path) as (client, _):
        csrf = await login(client)
        headers = write_headers(csrf)
        too_large = await client.post(
            "/admin/v1/auth/login",
            content=b"x" * (16 * 1024 + 1),
            headers={"Content-Type": "application/json", "Origin": ORIGIN},
        )
        assert too_large.status_code == 413
        bad_media = await client.put(
            "/admin/v1/config", content=b"{}", headers={**headers, "Content-Type": "text/plain"}
        )
        assert bad_media.status_code == 415
        bad_json = await client.put(
            "/admin/v1/config", content=b"{", headers={**headers, "Content-Type": "application/json"}
        )
        assert bad_json.status_code == 400
        deeply_nested = await client.put(
            "/admin/v1/config",
            content=b'{"x":' + b"[" * 1500 + b"0" + b"]" * 1500 + b"}",
            headers={**headers, "Content-Type": "application/json"},
        )
        assert deeply_nested.status_code == 400
        busy = await client.post(
            "/admin/v1/fuzz-runs", json={"profile_id": "core-demo-v1", "seed": 1}, headers=headers
        )
        assert busy.status_code == 409 and busy.json()["error"]["code"] == "FUZZ_BUSY"
        assert (await client.get("/admin/v1/fuzz-runs")).json() == {"items": [], "next_cursor": None}
        assert (await client.get("/admin/v1/fuzz-runs/bad")).status_code == 404
        client._transport.client = ("192.0.2.1", 53421)
        assert (await client.get("/")).status_code == 403
        assert (await client.get("/admin/v1/auth/session")).status_code == 403


@pytest.mark.asyncio
async def test_login_counter_and_session_expiry(tmp_path):
    db = Database(tmp_path / "auth.sqlite3", writer_budget_ms=5000)
    await db.initialize()
    now = [1_000_000]
    auth = AuthService(db, b"s" * 32, clock=lambda: now[0])
    await auth.bootstrap_admin("operator", PASSWORD)
    for _ in range(10):
        with pytest.raises(Exception):
            await auth.login("operator", "wrong-password", "127.0.0.1")
    with pytest.raises(Exception) as exc:
        await auth.login("operator", PASSWORD, "127.0.0.1")
    assert exc.value.code == "ADMIN_BUSY"
    now[0] += 60_000
    info = await auth.login("operator", PASSWORD, "127.0.0.1")
    token = info.token
    now[0] += IDLE_MS
    with pytest.raises(Exception):
        await auth.session(token)
    second = await auth.login("operator", PASSWORD, "127.0.0.1")
    with pytest.raises(AuthError) as malformed:
        await auth.session("é")
    assert malformed.value.status == 401
    assert not csrf_matches(second.csrf_token, "é")
    now[0] += ABSOLUTE_MS
    with pytest.raises(Exception):
        await auth.session(second.token)
    await db.close()


@pytest.mark.asyncio
async def test_hash_cancellation_retains_slot_until_thread_finishes(tmp_path):
    auth = AuthService(Database(tmp_path / "unused.sqlite3"), b"s" * 32)
    started = threading.Event()
    release = threading.Event()
    second_started = threading.Event()

    def blocking_hash():
        started.set()
        release.wait(3)
        return "done"

    def second_hash():
        second_started.set()
        release.wait(3)
        return "second"

    pending = asyncio.create_task(auth._hash_job(blocking_hash))
    try:
        assert await asyncio.to_thread(started.wait, 3)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        second = asyncio.create_task(auth._hash_job(second_hash))
        assert await asyncio.to_thread(second_started.wait, 3)
        with pytest.raises(AuthError) as busy:
            await auth._hash_job(lambda: "third")
        assert busy.value.code == "ADMIN_BUSY"
    finally:
        release.set()
    assert await second == "second"
    await asyncio.sleep(0.05)
    assert await auth._hash_job(lambda: "available") == "available"


@pytest.mark.asyncio
async def test_security_clock_prevents_session_extension_after_rollback(tmp_path):
    db = Database(tmp_path / "auth.sqlite3", writer_budget_ms=5000)
    await db.initialize()
    now = [1_000_000]
    auth = AuthService(db, b"s" * 32, clock=lambda: now[0])
    await auth.bootstrap_admin("operator", PASSWORD)
    session = await auth.login("operator", PASSWORD, "127.0.0.1", prior_token="é")
    with pytest.raises(AuthError):
        await auth.logout("é", session.admin_id)
    async with db.write() as conn:
        await effective_now(conn, now[0] + IDLE_MS)
    with pytest.raises(AuthError) as expired:
        await auth.session(session.token)
    assert expired.value.status == 401
    await db.close()


@pytest.mark.asyncio
async def test_production_host_cookie_flags(tmp_path):
    origin = "https://admin.example.test"
    settings = Settings(
        data_dir=tmp_path,
        registry_file=tmp_path / "registry.json",
        admin_origin=origin,
        mode="production",
        rate_secret_file=tmp_path / "rate.key",
    )
    settings.rate_secret_file.write_bytes(b"s" * 32)
    registry = Registry.model_validate({"upstreams": []})
    db = Database(settings.db_path, writer_budget_ms=5000)
    await db.initialize()
    await AuthService(db, b"s" * 32).bootstrap_admin("operator", PASSWORD)
    app = create_management(settings, db, registry, NoopFuzz())
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 53421))
        async with httpx.AsyncClient(transport=transport, base_url=origin) as client:
            response = await client.post(
                "/admin/v1/auth/login",
                json={"username": "operator", "password": PASSWORD},
                headers={"Origin": origin},
            )
            assert response.status_code == 200
            cookie = response.headers["Set-Cookie"]
            assert cookie.startswith("__Host-shield_session=")
            assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=strict" in cookie
            assert "Domain=" not in cookie and "Path=/" in cookie
    await db.close()


def test_operator_cli_bootstrap_reset_and_apply(tmp_path):
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "upstreams": [
                    {"id": "origin", "name": "Origin", "scheme": "http", "host": "127.0.0.1", "port": 9000}
                ]
            }
        ),
        encoding="utf-8",
    )
    config = tmp_path / "config.json"
    config.write_text(json.dumps(DOCUMENT), encoding="utf-8")
    password = tmp_path / "password.txt"
    password.write_text(PASSWORD, encoding="utf-8")
    env = os.environ.copy()
    env.update(
        {
            "SHIELD_DATA_DIR": str(tmp_path / "runtime"),
            "SHIELD_REGISTRY_FILE": str(registry),
            "SHIELD_ADMIN_ORIGIN": ORIGIN,
            "SHIELD_MODE": "development",
        }
    )
    backend = Path(__file__).resolve().parents[2]

    def command(*args):
        return subprocess.run(
            [sys.executable, "-m", "shield_api.cli", *args],
            cwd=backend,
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )

    assert command("migrate").returncode == 0
    assert (tmp_path / "runtime" / "rate.key").stat().st_size == 32
    assert (
        command("bootstrap-admin", "--username", "operator", "--password-file", str(password)).returncode == 0
    )
    assert (
        command("bootstrap-admin", "--username", "operator", "--password-file", str(password)).returncode == 1
    )
    assert command("apply-config", "--config-file", str(config), "--expected-version", "none").returncode == 0
    assert command("apply-config", "--config-file", str(config), "--expected-version", "none").returncode == 1
    assert (
        command("reset-password", "--username", "operator", "--password-file", str(password)).returncode == 0
    )
