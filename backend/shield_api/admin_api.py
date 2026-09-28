"""Private management listener and authenticated API."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import ipaddress
import json
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from .admin_auth import AuthError, AuthService, SessionInfo, csrf_matches
from .config import ConfigConflict, ConfigStore
from .contracts import ConfigInvalid, Registry
from .db import Database, StorageUnavailable, read_effective_now
from .protection import BanError, ProtectionService
from .settings import Settings
from .fuzz_jobs import FuzzBusy, FuzzInvalid


MAX_GENERAL_BODY = 512 * 1024
MAX_LOGIN_BODY = 16 * 1024
MAX_HEADERS = 100
MAX_HEADER_BYTES = 32 * 1024
MAX_PAGE = 100
MAX_RANGE_MS = 7 * 86_400_000


class ApiFailure(Exception):
    def __init__(self, status: int, code: str, message: str = "Request rejected") -> None:
        self.status = status
        self.code = code
        self.message = message


def _error(status: int, code: str, *, request_id: str = "") -> JSONResponse:
    response = JSONResponse(
        {"error": {"code": code, "message": "Request rejected", "request_id": request_id}}, status_code=status
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Request-ID"] = request_id
    return response


def _integer(value: Any, *, minimum: int, maximum: int, code: str = "BAD_REQUEST") -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ApiFailure(400, code)
    return value


def _query_int(value: str | None, *, default: int, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    if not value or len(value) > 19 or not value.isascii() or not value.isdecimal():
        raise ApiFailure(400, "BAD_REQUEST")
    return _integer(int(value), minimum=minimum, maximum=maximum)


def _page_limit(request: Request) -> int:
    return _query_int(request.query_params.get("limit"), default=50, minimum=1, maximum=MAX_PAGE)


def _cursor_encode(secret: bytes, payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    mac = hmac.new(secret, raw, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(raw + mac).rstrip(b"=").decode("ascii")


def _cursor_payload(secret: bytes, token: str) -> dict[str, Any]:
    if len(token) > 512:
        raise ApiFailure(400, "BAD_REQUEST")
    try:
        data = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        raw, mac = data[:-32], data[-32:]
        if len(mac) != 32 or not hmac.compare_digest(mac, hmac.new(secret, raw, hashlib.sha256).digest()):
            raise ValueError
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError
        return payload
    except (ValueError, UnicodeError, TypeError, binascii.Error) as exc:
        raise ApiFailure(400, "BAD_REQUEST") from exc


def _cursor_decode(secret: bytes, token: str | None, binding: dict[str, Any]) -> tuple[int, int | str] | None:
    if token is None:
        return None
    payload = _cursor_payload(secret, token)
    if (
        payload.get("binding") != binding
        or type(payload.get("at")) is not int
        or type(payload.get("id")) not in (int, str)
    ):
        raise ApiFailure(400, "BAD_REQUEST")
    return payload["at"], payload["id"]


async def _safe_json_body(request: Request) -> dict[str, Any]:
    try:
        value = json.loads(await request.body())
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ApiFailure(400, "BAD_REQUEST") from exc
    if not isinstance(value, dict):
        raise ApiFailure(400, "BAD_REQUEST")
    pending, nodes = [(value, 0)], 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if depth > 32 or nodes > 50_000:
            raise ApiFailure(400, "BAD_REQUEST")
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
    return value


def create_management(
    settings: Settings | None = None,
    db: Database | None = None,
    registry: Registry | None = None,
    fuzz_service: Any | None = None,
) -> FastAPI:
    """Build the private app. Settings and files are loaded only in lifespan."""
    state: dict[str, Any] = {}
    slots: asyncio.Queue[None] = asyncio.Queue(maxsize=20)
    for _ in range(20):
        slots.put_nowait(None)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        local_settings = settings or Settings.from_env()
        local_db = db or Database(local_settings.db_path)
        if not local_db.path.is_file():
            raise StorageUnavailable("Runtime store has not been migrated")
        try:
            async with local_db.read() as conn:
                row = await (
                    await conn.execute("SELECT singleton FROM runtime_config WHERE singleton=1")
                ).fetchone()
            if row is None:
                raise StorageUnavailable("Runtime store has not been migrated")
        except StorageUnavailable:
            raise
        except Exception as exc:
            raise StorageUnavailable("Runtime store is unavailable") from exc
        local_registry = registry or local_settings.load_registry()
        secret = local_settings.load_rate_secret()
        state.update(
            settings=local_settings,
            db=local_db,
            registry=local_registry,
            secret=secret,
            config=ConfigStore(local_db, local_registry),
            auth=AuthService(local_db, secret),
            protection=ProtectionService(local_db, secret),
        )
        if fuzz_service is None:
            try:
                from .fuzz_jobs import FuzzJobs

                state["fuzz"] = FuzzJobs(local_db, local_settings)
            except ImportError:
                state["fuzz"] = None
        else:
            state["fuzz"] = fuzz_service
        if state["fuzz"] is not None:
            await state["fuzz"].startup()
        try:
            yield
        finally:
            if state.get("fuzz") is not None:
                await state["fuzz"].close()
            if db is None:
                await local_db.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def ingress(request: Request, call_next):
        if state.get("settings") is not None and state["settings"].mode == "development":
            try:
                local_peer = bool(request.client and ipaddress.ip_address(request.client.host).is_loopback)
            except ValueError:
                local_peer = False
            if not local_peer:
                return Response(status_code=403, headers={"Cache-Control": "no-store"})
        if not request.url.path.startswith("/admin/v1"):
            return await call_next(request)
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        try:
            slots.get_nowait()
        except asyncio.QueueEmpty:
            return _error(503, "ADMIN_BUSY", request_id=request_id)
        try:
            headers = request.scope.get("headers", [])
            if (
                len(headers) > MAX_HEADERS
                or sum(len(key) + len(value) for key, value in headers) > MAX_HEADER_BYTES
            ):
                return _error(431, "HEADERS_TOO_LARGE", request_id=request_id)
            if request.url.path != "/admin/v1/auth/login":
                await require_session(request, write=request.method in ("POST", "PUT", "PATCH", "DELETE"))
            if request.method in ("POST", "PUT", "PATCH", "DELETE"):
                if (
                    request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    != "application/json"
                ):
                    return _error(415, "CONTENT_TYPE_NOT_ALLOWED", request_id=request_id)
                cap = MAX_LOGIN_BODY if request.url.path == "/admin/v1/auth/login" else MAX_GENERAL_BODY
                chunks: list[bytes] = []
                total = 0
                try:
                    async with asyncio.timeout(10):
                        async for chunk in request.stream():
                            total += len(chunk)
                            if total > cap:
                                return _error(413, "BODY_TOO_LARGE", request_id=request_id)
                            chunks.append(chunk)
                except TimeoutError:
                    return _error(408, "REQUEST_TIMEOUT", request_id=request_id)
                request._body = b"".join(chunks)
            response = await call_next(request)
            if response.status_code in (404, 405):
                code = "METHOD_NOT_ALLOWED" if response.status_code == 405 else "NOT_FOUND"
                replacement = _error(response.status_code, code, request_id=request_id)
                if response.status_code == 405 and "allow" in response.headers:
                    replacement.headers["Allow"] = response.headers["allow"]
                return replacement
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Request-ID"] = request_id
            return response
        except (
            ApiFailure,
            AuthError,
            BanError,
            ConfigInvalid,
            ConfigConflict,
            StorageUnavailable,
            FuzzBusy,
            FuzzInvalid,
        ) as exc:
            if isinstance(exc, ApiFailure):
                status, code = exc.status, exc.code
            elif isinstance(exc, (AuthError, BanError)):
                status, code = exc.status, exc.code
            elif isinstance(exc, ConfigInvalid):
                status, code = 422, "CONFIG_INVALID"
            elif isinstance(exc, ConfigConflict):
                status, code = 409, "CONFIG_CONFLICT"
            elif isinstance(exc, FuzzBusy):
                status, code = 409, "FUZZ_BUSY"
            elif isinstance(exc, FuzzInvalid):
                status, code = 400, "BAD_REQUEST"
            else:
                status, code = 503, "STORAGE_UNAVAILABLE"
            return _error(status, code, request_id=request_id)
        finally:
            slots.put_nowait(None)

    def services() -> dict[str, Any]:
        if not state:
            raise ApiFailure(503, "STORAGE_UNAVAILABLE")
        return state

    def cookie_name() -> str:
        return (
            "__Host-shield_session" if services()["settings"].mode == "production" else "shield_dev_session"
        )

    def require_origin(request: Request) -> None:
        if request.headers.get("origin") != services()["settings"].admin_origin:
            raise ApiFailure(403, "CSRF_REJECTED")

    async def require_session(request: Request, *, write: bool = False) -> SessionInfo:
        token = request.cookies.get(cookie_name())
        info = await services()["auth"].session(token)
        if write:
            require_origin(request)
            if not csrf_matches(info.csrf_token, request.headers.get("x-csrf-token")):
                raise ApiFailure(403, "CSRF_REJECTED")
        return info

    async def service_id() -> str:
        _, document = await services()["config"].load_desired()
        if document is None:
            raise ApiFailure(503, "CONFIG_UNAVAILABLE")
        return document.service.id

    @app.get("/_shield/health/live")
    async def live():
        return Response(status_code=200)

    @app.get("/_shield/health/ready")
    async def ready():
        if not state:
            return Response(status_code=503)
        try:
            async with state["db"].read() as conn:
                await (await conn.execute("SELECT 1 FROM security_clock WHERE singleton=1")).fetchone()
            return Response(status_code=200)
        except Exception:
            return Response(status_code=503)

    @app.post("/admin/v1/auth/login")
    async def login(request: Request):
        require_origin(request)
        body = await _safe_json_body(request)
        if (
            set(body) != {"username", "password"}
            or type(body["username"]) is not str
            or type(body["password"]) is not str
        ):
            raise ApiFailure(400, "BAD_REQUEST")
        peer = request.client.host if request.client else ""
        try:
            info = await services()["auth"].login(
                body["username"], body["password"], peer, request.cookies.get(cookie_name())
            )
        except ValueError as exc:
            if isinstance(exc, AuthError):
                raise
            raise ApiFailure(400, "BAD_REQUEST") from exc
        response = JSONResponse(info.public())
        response.set_cookie(
            cookie_name(),
            info.token,
            secure=services()["settings"].mode == "production",
            httponly=True,
            samesite="strict",
            path="/",
            max_age=8 * 60 * 60,
        )
        return response

    @app.get("/admin/v1/auth/session")
    async def session(request: Request):
        return (await require_session(request)).public()

    @app.post("/admin/v1/auth/logout")
    async def logout(request: Request):
        info = await require_session(request, write=True)
        await services()["auth"].logout(request.cookies[cookie_name()], info.admin_id)
        response = Response(status_code=204)
        response.delete_cookie(cookie_name(), path="/")
        return response

    @app.get("/admin/v1/registry")
    async def get_registry(request: Request):
        await require_session(request)
        return {
            "upstreams": [{"id": item.id, "name": item.name} for item in services()["registry"].upstreams]
        }

    @app.get("/admin/v1/config")
    async def get_config(request: Request):
        await require_session(request)
        version, document = await services()["config"].load_desired()
        return {"version": version, "document": document.model_dump(mode="json") if document else None}

    @app.put("/admin/v1/config", status_code=202)
    async def put_config(request: Request):
        info = await require_session(request, write=True)
        body = await _safe_json_body(request)
        if (
            set(body) != {"expected_version", "document"}
            or (
                body["expected_version"] is not None
                and (type(body["expected_version"]) is not int or body["expected_version"] < 1)
            )
            or not isinstance(body["document"], dict)
        ):
            raise ApiFailure(422, "CONFIG_INVALID")
        pending = await services()["config"].apply_config(
            body["expected_version"], body["document"], info.admin_id
        )
        return pending.model_dump()

    @app.get("/admin/v1/status")
    async def get_status(request: Request):
        await require_session(request)
        return asdict(await services()["config"].status())

    @app.get("/admin/v1/bans")
    async def get_bans(request: Request):
        await require_session(request)
        state_filter = request.query_params.get("state", "active")
        if state_filter not in ("active", "expired", "revoked", "all"):
            raise ApiFailure(400, "BAD_REQUEST")
        limit = _page_limit(request)
        sid = await service_id()
        binding = {"kind": "bans", "state": state_filter, "service": sid}
        cursor = _cursor_decode(services()["secret"], request.query_params.get("cursor"), binding)
        now_ms = int(time.time() * 1000)
        async with services()["db"].read() as conn:
            now_ms = await read_effective_now(conn, now_ms)
            args: list[Any] = [sid]
            where = "service_id=?"
            if state_filter == "active":
                where += " AND revoked_at_ms IS NULL AND expires_at_ms>?"
                args.append(now_ms)
            elif state_filter == "expired":
                where += " AND revoked_at_ms IS NULL AND expires_at_ms<=?"
                args.append(now_ms)
            elif state_filter == "revoked":
                where += " AND revoked_at_ms IS NOT NULL"
            if cursor:
                where += " AND (created_at_ms<? OR (created_at_ms=? AND ban_id<?))"
                args.extend([cursor[0], cursor[0], cursor[1]])
            rows = await (
                await conn.execute(
                    f"SELECT * FROM bans WHERE {where} ORDER BY created_at_ms DESC,ban_id DESC LIMIT ?",
                    (*args, limit + 1),
                )
            ).fetchall()
        from .protection import _ban_view

        items = [_ban_view(row, now_ms).model_dump() for row in rows[:limit]]
        next_cursor = (
            _cursor_encode(
                services()["secret"],
                {"binding": binding, "at": rows[limit - 1]["created_at_ms"], "id": rows[limit - 1]["ban_id"]},
            )
            if len(rows) > limit
            else None
        )
        return {"items": items, "next_cursor": next_cursor}

    @app.post("/admin/v1/bans", status_code=201)
    async def post_ban(request: Request):
        info = await require_session(request, write=True)
        body = await _safe_json_body(request)
        if set(body) not in (
            {"ip", "duration_seconds", "reason"},
            {"client_digest", "duration_seconds", "reason"},
        ):
            raise ApiFailure(400, "BAD_REQUEST")
        duration = _integer(body["duration_seconds"], minimum=30, maximum=3600)
        reason = body["reason"]
        if reason not in ("operator_action", "demo_test"):
            raise ApiFailure(400, "BAD_REQUEST")
        key = "ip" if "ip" in body else "client_digest"
        if type(body[key]) is not str:
            raise ApiFailure(400, "BAD_REQUEST")
        ban = await services()["protection"].create_manual_ban(
            {key: body[key]},
            duration,
            reason,
            info.admin_id,
            int(time.time() * 1000),
            service_id=await service_id(),
        )
        return ban.model_dump()

    @app.post("/admin/v1/bans/{ban_id}/revoke")
    async def revoke_ban(request: Request, ban_id: str):
        info = await require_session(request, write=True)
        if await _safe_json_body(request):
            raise ApiFailure(400, "BAD_REQUEST")
        result = await services()["protection"].revoke_ban(ban_id, info.admin_id, int(time.time() * 1000))
        return result.model_dump()

    @app.get("/admin/v1/events")
    async def get_events(request: Request):
        await require_session(request)
        kind = request.query_params.get("kind", "request")
        if kind not in ("request", "security"):
            raise ApiFailure(400, "BAD_REQUEST")
        now_ms = int(time.time() * 1000)
        cursor_token = request.query_params.get("cursor")
        cursor_binding = (
            _cursor_payload(services()["secret"], cursor_token).get("binding")
            if cursor_token is not None
            else None
        )
        if cursor_binding is not None and (
            not isinstance(cursor_binding, dict)
            or cursor_binding.get("kind") != kind
            or type(cursor_binding.get("from_ms")) is not int
            or type(cursor_binding.get("to_ms")) is not int
        ):
            raise ApiFailure(400, "BAD_REQUEST")
        from_ms = _query_int(
            request.query_params.get("from_ms"),
            default=cursor_binding["from_ms"] if cursor_binding else now_ms - MAX_RANGE_MS,
            minimum=0,
            maximum=2**63 - 1,
        )
        to_ms = _query_int(
            request.query_params.get("to_ms"),
            default=cursor_binding["to_ms"] if cursor_binding else now_ms,
            minimum=0,
            maximum=2**63 - 1,
        )
        if not from_ms < to_ms or to_ms - from_ms > MAX_RANGE_MS:
            raise ApiFailure(400, "BAD_REQUEST")
        limit = _page_limit(request)
        binding = {"kind": kind, "from_ms": from_ms, "to_ms": to_ms}
        cursor = _cursor_decode(services()["secret"], cursor_token, binding)
        table = "request_events" if kind == "request" else "security_events"
        where = "at_ms>=? AND at_ms<?"
        args: list[Any] = [from_ms, to_ms]
        if cursor:
            where += " AND (at_ms<? OR (at_ms=? AND id<?))"
            args.extend([cursor[0], cursor[0], cursor[1]])
        async with services()["db"].read() as conn:
            rows = await (
                await conn.execute(
                    f"SELECT * FROM {table} WHERE {where} ORDER BY at_ms DESC,id DESC LIMIT ?",
                    (*args, limit + 1),
                )
            ).fetchall()
            earliest = await (await conn.execute(f"SELECT min(at_ms) AS at_ms FROM {table}")).fetchone()
        items = []
        for row in rows[:limit]:
            item = dict(row)
            if kind == "security":
                item["safe_details"] = json.loads(item.pop("safe_details_json"))
            else:
                item["origin_attempted"] = bool(item["origin_attempted"])
                item["truncated"] = bool(item["truncated"])
            items.append(item)
        next_cursor = (
            _cursor_encode(
                services()["secret"],
                {"binding": binding, "at": rows[limit - 1]["at_ms"], "id": rows[limit - 1]["id"]},
            )
            if len(rows) > limit
            else None
        )
        return {
            "items": items,
            "next_cursor": next_cursor,
            "earliest_retained_ms": earliest["at_ms"],
            "telemetry_complete": False,
        }

    @app.post("/admin/v1/fuzz-runs", status_code=202)
    async def start_fuzz(request: Request):
        info = await require_session(request, write=True)
        body = await _safe_json_body(request)
        if (
            set(body) != {"profile_id", "seed"}
            or body["profile_id"] != "core-demo-v1"
            or type(body["seed"]) is not int
            or not 0 <= body["seed"] <= 2_147_483_647
        ):
            raise ApiFailure(400, "BAD_REQUEST")
        fuzz = services()["fuzz"]
        if fuzz is None:
            raise ApiFailure(503, "STORAGE_UNAVAILABLE")
        result = await fuzz.start(body["profile_id"], body["seed"], info.admin_id)
        return {"run_id": result.run_id, "state": result.state}

    @app.get("/admin/v1/fuzz-runs")
    async def list_fuzz(request: Request):
        await require_session(request)
        fuzz = services()["fuzz"]
        if fuzz is None:
            raise ApiFailure(503, "STORAGE_UNAVAILABLE")
        cursor = request.query_params.get("cursor")
        if cursor is not None and len(cursor) > 512:
            raise ApiFailure(400, "BAD_REQUEST")
        try:
            return await fuzz.list(cursor, _page_limit(request))
        except (ValueError, binascii.Error) as exc:
            raise ApiFailure(400, "BAD_REQUEST") from exc

    @app.get("/admin/v1/fuzz-runs/{run_id}")
    async def detail_fuzz(request: Request, run_id: str):
        await require_session(request)
        fuzz = services()["fuzz"]
        if fuzz is None:
            raise ApiFailure(503, "STORAGE_UNAVAILABLE")
        detail = await fuzz.detail(run_id)
        if detail is None:
            raise ApiFailure(404, "RUN_NOT_FOUND")
        return detail

    dist = Path(__file__).resolve().parents[2] / "dist"

    @app.get("/")
    async def index():
        if not (dist / "index.html").is_file():
            return Response(status_code=503)
        response = FileResponse(dist / "index.html")
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        )
        return response

    @app.get("/{asset_path:path}")
    async def assets(asset_path: str):
        if (
            asset_path.startswith("admin/")
            or asset_path.startswith("_shield/")
            or ".." in Path(asset_path).parts
        ):
            return Response(status_code=404)
        path = (dist / asset_path).resolve()
        if not path.is_relative_to(dist.resolve()) or not path.is_file():
            return Response(status_code=404)
        response = FileResponse(path)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        )
        return response

    return app
