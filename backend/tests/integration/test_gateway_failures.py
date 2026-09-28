"""Gateway failure paths on loopback sockets and isolated SQLite state."""

from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi import FastAPI, Request
from filelock import Timeout as LockTimeout
from starlette.responses import Response, StreamingResponse

from shield_api.contracts import Registry
from shield_api.db import Database
from shield_api.gateway import create_gateway
from shield_api.settings import Settings
from tests.integration.test_gateway_network import gateway_for
from tests.network_support import serve


async def _event_for(app, db, request_id):
    for _ in range(100):
        await app.state.sink.flush()
        async with db.read() as conn:
            row = await (
                await conn.execute("SELECT * FROM request_events WHERE request_id=?", (request_id,))
            ).fetchone()
        if row is not None:
            return row
        await asyncio.sleep(0.02)
    raise AssertionError(f"No completion event for {request_id}")


async def test_early_blocks_have_zero_origin_receipts(tmp_path):
    origin = FastAPI()
    receipts = [0]

    @origin.api_route("/{path:path}", methods=["GET", "POST"])
    async def reply(request: Request, path: str):
        receipts[0] += 1
        return Response("ok")

    async with serve(origin) as (_, port):
        async with gateway_for(tmp_path, port) as (client, app, db):
            blocked = [
                await client.get("/%2f"),
                await client.post("/ok", content=b"x" * 1025),
                await client.get("/ok", headers={"Host": "wrong.localhost"}),
            ]
            assert [item.status_code for item in blocked] == [400, 413, 404]
            assert receipts == [0]
            for response in blocked:
                event = await _event_for(app, db, response.headers["x-request-id"])
                assert not event["origin_attempted"]
                assert event["decision"] == "blocked"
            assert app.state.permits._value == 50


async def test_preheader_timeout_unavailable_origin_and_declared_oversize(tmp_path):
    origin = FastAPI()

    @origin.get("/slow")
    async def slow():
        await asyncio.sleep(0.5)
        return Response("late")

    @origin.get("/declared-large")
    async def declared_large():
        return StreamingResponse(iter(()), headers={"Content-Length": str(10_485_761)})

    async with serve(origin) as (_, port):
        async with gateway_for(tmp_path / "live", port) as (client, app, db):
            upstreams = []
            original_forward = app.state.forwarder.forward

            async def capture(request):
                upstream = await original_forward(request)
                upstreams.append(upstream)
                return upstream

            app.state.forwarder.forward = capture
            app.state.forwarder.client.timeout = httpx.Timeout(0.1, connect=0.1)
            timed = await client.get("/slow")
            assert timed.status_code == 504
            assert timed.json()["error"]["code"] == "UPSTREAM_TIMEOUT"
            event = await _event_for(app, db, timed.headers["x-request-id"])
            assert event["origin_attempted"] and event["decision"] == "gateway_error"

            oversized = await client.get("/declared-large")
            assert oversized.status_code == 502
            assert oversized.json()["error"]["code"] == "UPSTREAM_RESPONSE_TOO_LARGE"
            event = await _event_for(app, db, oversized.headers["x-request-id"])
            assert event["origin_attempted"] and not event["truncated"]
            assert len(upstreams) == 1 and upstreams[0].is_closed
            assert app.state.permits._value == 50

    async with gateway_for(tmp_path / "closed", port) as (client, app, db):

        def connection_error(request):
            raise httpx.ConnectError("synthetic connection failure", request=request)

        old_client = app.state.forwarder.client
        app.state.forwarder.client = httpx.AsyncClient(
            transport=httpx.MockTransport(connection_error),
            trust_env=False,
        )
        await old_client.aclose()
        failed = await client.get("/unavailable")
        assert failed.status_code == 502
        assert failed.json()["error"]["code"] == "UPSTREAM_UNAVAILABLE"
        event = await _event_for(app, db, failed.headers["x-request-id"])
        assert event["origin_attempted"] and event["upstream_status"] is None
        assert app.state.permits._value == 50


async def test_overlong_stream_truncates_and_releases_permit(tmp_path):
    origin = FastAPI()

    @origin.get("/long")
    async def long_stream():
        async def chunks():
            for _ in range(11):
                yield b"x" * 1_048_576

        return StreamingResponse(chunks(), media_type="application/octet-stream")

    async with serve(origin) as (_, port):
        async with gateway_for(tmp_path, port) as (client, app, db):
            upstreams = []
            original_forward = app.state.forwarder.forward

            async def capture(request):
                upstream = await original_forward(request)
                upstreams.append(upstream)
                return upstream

            app.state.forwarder.forward = capture
            request_id = None
            with pytest.raises(httpx.HTTPError):
                async with client.stream("GET", "/long") as response:
                    request_id = response.headers["x-request-id"]
                    async for _ in response.aiter_raw():
                        pass
            assert request_id is not None
            event = await _event_for(app, db, request_id)
            assert event["truncated"] and event["origin_attempted"]
            assert event["response_bytes"] > 10_485_760
            assert len(upstreams) == 1 and upstreams[0].is_closed
            assert app.state.permits._value == 50


async def test_slow_client_disconnect_releases_permit_without_origin(tmp_path):
    origin = FastAPI()
    receipts = [0]

    @origin.post("/upload")
    async def upload(request: Request):
        receipts[0] += 1
        return Response(await request.body())

    async with serve(origin) as (_, port):
        async with gateway_for(tmp_path, port) as (client, app, db):
            host, gateway_port = client.base_url.host, client.base_url.port
            reader, writer = await asyncio.open_connection(host, gateway_port)
            del reader
            writer.write(b"POST /upload HTTP/1.1\r\nHost: api.localhost\r\nContent-Length: 10\r\n\r\nabc")
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            for _ in range(100):
                await app.state.sink.flush()
                async with db.read() as conn:
                    rows = await (
                        await conn.execute(
                            "SELECT decision,origin_attempted FROM request_events WHERE method='POST'"
                        )
                    ).fetchall()
                if rows:
                    break
                await asyncio.sleep(0.02)
            assert receipts == [0]
            assert len(rows) == 1 and rows[0]["decision"] == "client_disconnected"
            assert not rows[0]["origin_attempted"]
            assert app.state.permits._value == 50


async def test_two_inspections_bound_thread_work_and_third_request(tmp_path, monkeypatch):
    from shield_api import gateway as gateway_module

    origin = FastAPI()
    receipts = [0]

    @origin.post("/json")
    async def json_route(request: Request):
        receipts[0] += 1
        return Response(await request.body())

    document = {
        "schema_version": 1,
        "service": {
            "id": "test",
            "name": "Test",
            "public_host": "api.localhost",
            "upstream_id": "demo-origin",
            "enabled": True,
            "unmatched_action": "baseline",
            "max_body_bytes": 1024,
            "ip_rate": {"limit": 1000, "window_seconds": 60},
            "abuse": {},
            "routes": [
                {
                    "id": "json",
                    "name": "JSON",
                    "path": "/json",
                    "methods": ["POST"],
                    "max_body_bytes": 1024,
                    "content_types": ["application/json"],
                    "json_schema": {
                        "type": "object",
                        "required": ["x"],
                        "properties": {"x": {"type": "integer"}},
                    },
                }
            ],
        },
    }
    original = gateway_module.validate_payload
    entered = asyncio.Event()
    release = threading.Event()
    count = [0]
    guard = threading.Lock()
    loop = asyncio.get_running_loop()

    def slow_validation(*args, **kwargs):
        with guard:
            count[0] += 1
            if count[0] == 2:
                loop.call_soon_threadsafe(entered.set)
        release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(gateway_module, "validate_payload", slow_validation)
    async with serve(origin) as (_, port):
        async with gateway_for(tmp_path, port, document) as (client, app, db):
            first = asyncio.create_task(client.post("/json", json={"x": 1}))
            second = asyncio.create_task(client.post("/json", json={"x": 2}))
            try:
                await asyncio.wait_for(entered.wait(), 3)
                third = await client.post("/json", json={"x": 3})
                assert third.status_code == 503
                assert third.json()["error"]["code"] == "GATEWAY_BUSY"
                assert receipts == [0]
            finally:
                release.set()
            assert (await first).status_code == 200
            assert (await second).status_code == 200
            assert receipts == [2]
            event = await _event_for(app, db, third.headers["x-request-id"])
            assert not event["origin_attempted"]
            assert app.state.inspections._value == 2
            assert app.state.permits._value == 50


@asynccontextmanager
async def _unconfigured_gateway(tmp_path):
    db = Database(tmp_path / "shield.sqlite3")
    await db.initialize()
    registry = Registry.model_validate(
        {
            "upstreams": [
                {
                    "id": "origin",
                    "name": "Origin",
                    "scheme": "http",
                    "host": "127.0.0.1",
                    "port": 9000,
                }
            ]
        }
    )
    settings = Settings(
        data_dir=tmp_path,
        registry_file=tmp_path / "registry.json",
        admin_origin="http://admin.localhost:8081",
        mode="development",
        rate_secret_file=tmp_path / "rate.key",
    )
    app = create_gateway(settings, db=db, registry=registry, rate_secret=b"x" * 32, runtime_lock=True)
    try:
        yield app, db, registry, settings
    finally:
        await db.close()


async def test_unready_without_config_and_exclusive_gateway_lock(tmp_path):
    async with _unconfigured_gateway(tmp_path) as (app, db, registry, settings):
        async with serve(app) as (url, _):
            async with httpx.AsyncClient(
                base_url=url, trust_env=False, headers={"Host": "api.localhost"}
            ) as client:
                assert (await client.get("/_shield/health/live")).status_code == 200
                assert (await client.get("/_shield/health/ready")).status_code == 503
                blocked = await client.get("/missing-config")
                assert blocked.status_code == 503
                assert blocked.json()["error"]["code"] == "CONFIG_UNAVAILABLE"
                event = await _event_for(app, db, blocked.headers["x-request-id"])
                assert not event["origin_attempted"]

            second = create_gateway(
                settings, db=db, registry=registry, rate_secret=b"x" * 32, runtime_lock=True
            )
            with pytest.raises(LockTimeout):
                async with second.router.lifespan_context(second):
                    pass

        # Failed startup did not retain the lock after the first gateway stopped.
        async with second.router.lifespan_context(second):
            assert second.state.config.snapshot is None
