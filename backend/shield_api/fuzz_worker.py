"""Fixed loopback-only profile. Never imports operator registry or live state."""

from __future__ import annotations

import asyncio
import json
import os
import random
import socket
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from filelock import FileLock, Timeout

from .config import ConfigStore
from .contracts import Config, RegisteredUpstream, Registry
from .db import Database
from .gateway import create_gateway
from .settings import Settings

PROFILE = "core-demo-v1"
MAX_STARTS = 100
MIN_SPACING = 0.2
MAX_REPORT = 65_536


def _socket() -> tuple[socket.socket, int]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    sock.setblocking(False)
    return sock, sock.getsockname()[1]


def _fixture_config(origin_port: int) -> tuple[Registry, Config]:
    registry = Registry(
        upstreams=(
            RegisteredUpstream(
                id="synthetic-origin",
                name="Synthetic origin",
                scheme="http",
                host="127.0.0.1",
                port=origin_port,
            ),
        )
    )

    def route(rid, path, methods, cap, schema=None, rate=None):
        return {
            "id": rid,
            "name": rid,
            "path": path,
            "methods": methods,
            "max_body_bytes": cap,
            "content_types": ["application/json"] if schema else [],
            "ip_rate": rate,
            "json_schema": schema,
        }

    credentials = {
        "type": "object",
        "required": ["username", "password"],
        "additionalProperties": False,
        "properties": {
            "username": {"type": "string", "minLength": 1},
            "password": {"type": "string", "minLength": 1},
        },
    }
    cart = {
        "type": "object",
        "required": ["owner", "quantity"],
        "additionalProperties": False,
        "properties": {
            "owner": {"type": "string"},
            "quantity": {"type": "integer", "minimum": 1, "maximum": 10},
        },
    }
    config = Config.model_validate(
        {
            "schema_version": 1,
            "service": {
                "id": "fuzz",
                "name": "Synthetic fuzz fixture",
                "public_host": "api.localhost",
                "upstream_id": "synthetic-origin",
                "enabled": True,
                "unmatched_action": "deny",
                "max_body_bytes": 1024,
                "ip_rate": {"limit": 100, "window_seconds": 60},
                "abuse": {
                    "auto_ban_enabled": True,
                    "strike_limit": 2,
                    "window_seconds": 60,
                    "ban_seconds": 30,
                },
                "routes": [
                    route("ok", "/ok", ["GET"], 0),
                    route("signup", "/signup", ["POST"], 512, credentials),
                    route("login", "/login", ["POST"], 512, credentials),
                    route("cart", "/cart", ["POST"], 512, cart),
                    route("rate", "/rate", ["GET"], 0, rate={"limit": 2, "window_seconds": 60}),
                ],
            },
        }
    )
    return registry, config


def _origin(receipts: list[int]) -> FastAPI:
    app = FastAPI(docs_url=None, openapi_url=None, redoc_url=None)

    @app.middleware("http")
    async def count(request: Request, call_next):
        receipts[0] += 1
        return await call_next(request)

    @app.get("/ok")
    @app.get("/rate")
    async def ok():
        return {"ok": True}

    @app.post("/signup")
    async def signup(request: Request):
        data = await request.json()
        return JSONResponse({"created": data["username"]}, status_code=201)

    @app.post("/login")
    async def login(request: Request):
        data = await request.json()
        if data["username"] == "alice" and data["password"] == "correct":
            return {"token": "fixture-alice"}
        return JSONResponse({"error": "invalid credentials"}, status_code=401)

    @app.post("/cart")
    async def cart(request: Request):
        data = await request.json()
        if request.headers.get("authorization") != "Bearer fixture-alice":
            return JSONResponse({"error": "unauthenticated"}, status_code=401)
        if data["owner"] != "alice":
            return JSONResponse({"error": "forbidden"}, status_code=403)
        return {"ok": True}

    return app


class Budget:
    def __init__(self) -> None:
        self.starts = 0
        self.last = 0.0

    async def before(self) -> None:
        if self.starts >= MAX_STARTS:
            raise RuntimeError("Request budget exhausted")
        if self.last:
            target = self.last + MIN_SPACING
            # Some event-loop clocks wake a timer slightly early, particularly
            # on Windows. Check the deadline rather than assuming sleep met it.
            while (remaining := target - time.monotonic()) > 0:
                await asyncio.sleep(remaining)
        self.last = time.monotonic()
        self.starts += 1


async def _run(run_id: str, seed: int, directory: Path) -> dict[str, object]:
    del run_id
    rng = random.Random(seed)
    receipts = [0]
    origin_sock, origin_port = _socket()
    gateway_sock, gateway_port = _socket()
    origin_server = uvicorn.Server(
        uvicorn.Config(_origin(receipts), log_level="critical", access_log=False, lifespan="on")
    )
    origin_task = asyncio.create_task(origin_server.serve(sockets=[origin_sock]))
    # This synthetic profile checks policy invariants, not disk scheduling.
    # Runtime contention with the default 100 ms budget is measured separately.
    db = Database(directory / "fixture.sqlite3", writer_budget_ms=1000)
    await db.initialize()
    registry, config = _fixture_config(origin_port)
    registry_file = directory / "registry.json"
    registry_file.write_text(json.dumps(registry.model_dump(mode="json")), encoding="utf-8")
    secret_file = directory / "rate.key"
    secret_file.write_bytes(os.urandom(32))
    settings = Settings(
        data_dir=directory,
        registry_file=registry_file,
        admin_origin="http://admin.localhost:8081",
        mode="development",
        rate_secret_file=secret_file,
    )
    # Freeze logical policy time inside a window so wall-clock boundaries cannot
    # make the same seeded rate/ban scenario produce a different result.
    fixture_now = (int(time.time() * 1000) // 60_000) * 60_000 + 10_000
    store = ConfigStore(db, registry, clock=lambda: fixture_now)
    await store.apply_config(None, config, "fixture")
    gateway_server = uvicorn.Server(
        uvicorn.Config(
            create_gateway(
                settings,
                db=db,
                registry=registry,
                rate_secret=secret_file.read_bytes(),
                runtime_lock=False,
                clock=lambda: fixture_now,
            ),
            log_level="critical",
            access_log=False,
            lifespan="on",
        )
    )
    gateway_task = asyncio.create_task(gateway_server.serve(sockets=[gateway_sock]))
    cases: list[dict[str, object]] = []
    budget = Budget()
    try:
        for _ in range(100):
            if origin_server.started and gateway_server.started:
                break
            await asyncio.sleep(0.02)
        if not origin_server.started or not gateway_server.started:
            raise RuntimeError("Fixture server did not start")
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{gateway_port}", trust_env=False, follow_redirects=False, timeout=5
        ) as client:

            async def case(
                case_id: str,
                expected_status: int,
                expected_receipts: int,
                method: str,
                path: str,
                *,
                body: bytes | None = None,
                content_type: str | None = None,
                authorization: str | None = None,
            ) -> None:
                await budget.before()
                before = receipts[0]
                headers = {"Host": "api.localhost"}
                if content_type:
                    headers["Content-Type"] = content_type
                if authorization:
                    headers["Authorization"] = authorization
                started = time.monotonic()
                try:
                    response = await client.request(method, path, headers=headers, content=body)
                    actual = response.status_code
                    request_id = response.headers.get("X-Request-ID")
                    delta = receipts[0] - before
                    passed = actual == expected_status and delta == expected_receipts
                    outcome = "passed" if passed else "failed"
                    actual_desc = f"status {actual}; origin receipts {delta}"
                except httpx.HTTPError:
                    request_id, delta, outcome, actual_desc = (
                        None,
                        receipts[0] - before,
                        "error",
                        "request error",
                    )
                cases.append(
                    {
                        "case_id": case_id,
                        "expected": f"status {expected_status}; origin receipts {expected_receipts}",
                        "actual": actual_desc,
                        "outcome": outcome,
                        "request_id": request_id,
                        "elapsed_ms": max(0, int((time.monotonic() - started) * 1000)),
                        "origin_receipt_delta": delta,
                    }
                )

            login_ok = b'{"username":"alice","password":"correct"}'
            malformed = rng.choice((b"{", b'{"username":', b'{"username":"alice",'))
            signup_name = f"user{rng.randrange(1_000_000):06d}"
            await case("control-before", 200, 1, "GET", "/ok")
            await case(
                "signup-valid",
                201,
                1,
                "POST",
                "/signup",
                body=json.dumps({"username": signup_name, "password": "secret"}).encode(),
                content_type="application/json",
            )
            await case(
                "login-valid", 200, 1, "POST", "/login", body=login_ok, content_type="application/json"
            )
            await case(
                "login-invalid-credentials",
                401,
                1,
                "POST",
                "/login",
                body=b'{"username":"alice","password":"wrong"}',
                content_type="application/json",
            )
            await case(
                "cart-own",
                200,
                1,
                "POST",
                "/cart",
                body=b'{"owner":"alice","quantity":1}',
                content_type="application/json",
                authorization="Bearer fixture-alice",
            )
            await case(
                "cart-cross-user",
                403,
                1,
                "POST",
                "/cart",
                body=b'{"owner":"bob","quantity":1}',
                content_type="application/json",
                authorization="Bearer fixture-alice",
            )
            await case(
                "cart-unauthenticated",
                401,
                1,
                "POST",
                "/cart",
                body=b'{"owner":"alice","quantity":1}',
                content_type="application/json",
            )
            await case("path-block", 404, 0, "GET", "/not-configured")
            await case("body-cap", 413, 0, "POST", "/login", body=b"x" * 513, content_type="application/json")
            await case(
                "invalid-json", 400, 0, "POST", "/login", body=malformed, content_type="application/json"
            )
            # Clear synthetic strikes before the independent schema and rate scenarios.
            async with db.write() as conn:
                await conn.execute("DELETE FROM abuse_counters")
                await conn.execute("DELETE FROM bans")
            await case(
                "schema-rejected",
                400,
                0,
                "POST",
                "/cart",
                body=b'{"owner":"alice","quantity":0}',
                content_type="application/json",
            )
            async with db.write() as conn:
                await conn.execute("DELETE FROM abuse_counters")
                await conn.execute("DELETE FROM bans")
            await case("rate-1", 200, 1, "GET", "/rate")
            await case("rate-2", 200, 1, "GET", "/rate")
            await case("rate-rejected-1", 429, 0, "GET", "/rate")
            await case("rate-rejected-2", 429, 0, "GET", "/rate")
            await case("temporary-ban", 403, 0, "GET", "/rate")
            # State cleanup occurs while fixture servers remain running.
            async with db.write() as conn:
                await conn.execute("DELETE FROM rate_counters")
                await conn.execute("DELETE FROM abuse_counters")
                await conn.execute("DELETE FROM bans")
            await case("control-after", 200, 1, "GET", "/ok")
        state = "passed" if all(c["outcome"] == "passed" for c in cases) and len(cases) == 17 else "failed"
        return {"state": state, "cases": cases}
    finally:
        gateway_server.should_exit = True
        origin_server.should_exit = True
        await asyncio.gather(gateway_task, origin_task, return_exceptions=True)
        await db.close()


async def _main(args: list[str]) -> int:
    if len(args) != 3:
        return 2
    run_id, seed_text, path_text = args
    try:
        uuid.UUID(run_id)
        if not seed_text.isdecimal() or not 0 <= int(seed_text) <= 2_147_483_647:
            return 2
        directory = Path(path_text).resolve(strict=True)
        if not directory.is_dir() or not directory.name.startswith("shield-fuzz-"):
            return 2
    except (ValueError, OSError):
        return 2
    lock = FileLock(str(Path(tempfile.gettempdir()) / "shield-api-fuzz-worker.lock"))
    try:
        lock.acquire(timeout=0)
    except Timeout:
        return 3
    loop = asyncio.get_running_loop()
    live = loop.create_future()

    def watch_parent() -> None:
        try:
            os.read(sys.stdin.fileno(), 1)
        except OSError:
            pass
        try:
            loop.call_soon_threadsafe(lambda: None if live.done() else live.set_result(None))
        except RuntimeError:
            pass  # The suite already ended and closed its event loop.

    threading.Thread(target=watch_parent, name="fuzz-parent-watch", daemon=True).start()
    suite = asyncio.create_task(_run(run_id, int(seed_text), directory))
    try:
        done, _ = await asyncio.wait({live, suite}, timeout=58, return_when=asyncio.FIRST_COMPLETED)
        if live in done or suite not in done:
            suite.cancel()
            await asyncio.gather(suite, return_exceptions=True)
            return 4
        report = await suite
        encoded = json.dumps(report, separators=(",", ":"), ensure_ascii=True).encode()
        if len(encoded) > MAX_REPORT:
            return 5
        (directory / "report.json").write_bytes(encoded)
        return 0
    except Exception:
        return 6
    finally:
        live.cancel()
        lock.release()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(sys.argv[1:])))
