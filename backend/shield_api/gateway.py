"""Public gateway composition. All admission checks precede origin contact."""

from __future__ import annotations

import asyncio
import ipaddress
import re
import time
import uuid
from contextlib import AsyncExitStack, asynccontextmanager
from urllib.parse import unquote_to_bytes

from fastapi import FastAPI, Request
from filelock import FileLock
from starlette.requests import ClientDisconnect
from starlette.responses import JSONResponse, Response, StreamingResponse

from .config import ConfigStore, HOST_RE
from .contracts import RequestEvent
from .db import Database, StorageUnavailable
from .events import EventSink
from .protection import ProtectionService
from .proxy import Forwarder, PreparedRequest, ProxyProblem, connection_tokens, response_headers
from .settings import Settings
from .validation import validate_payload

METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT"]


def canonical_path(raw: bytes) -> str:
    if not raw.startswith(b"/") or raw.startswith(b"//") or b"\\" in raw:
        raise ProxyProblem("BAD_PATH", 400)
    if re.search(rb"%(?![0-9a-fA-F]{2})", raw) or re.search(rb"%(?:2f|5c|25)", raw, re.I):
        raise ProxyProblem("BAD_PATH", 400)
    try:
        path = unquote_to_bytes(raw).decode("utf-8", "strict")
    except (UnicodeError, ValueError):
        raise ProxyProblem("BAD_PATH", 400) from None
    if "//" in path or any(ord(ch) < 32 or ord(ch) == 127 for ch in path) or "\\" in path:
        raise ProxyProblem("BAD_PATH", 400)
    if any(part in (".", "..") for part in path.split("/")):
        raise ProxyProblem("BAD_PATH", 400)
    return path


def canonical_host(headers):
    values = [v for k, v in headers if k.lower() == b"host"]
    if len(values) != 1:
        raise ProxyProblem("BAD_REQUEST", 400)
    try:
        host = values[0].decode("ascii").lower()
        if ":" in host:
            host, port = host.rsplit(":", 1)
            if not port.isdecimal() or not 1 <= int(port) <= 65535:
                raise ValueError()
        host = host.removesuffix(".")
        if not HOST_RE.fullmatch(host):
            raise ValueError()
        return host
    except (ValueError, UnicodeError):
        raise ProxyProblem("BAD_REQUEST", 400) from None


def client_identity(peer, headers, trusted):
    try:
        address = ipaddress.ip_address(peer)
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        if any(address in network for network in trusted):
            values = [v for k, v in headers if k.lower() == b"x-shield-client-ip"]
            if len(values) != 1:
                raise ValueError()
            address = ipaddress.ip_address(values[0].decode("ascii"))
            if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
                address = address.ipv4_mapped
        return str(address)
    except (ValueError, UnicodeError):
        raise ProxyProblem("BAD_REQUEST", 400) from None


def select_route(snapshot, method, path):
    segments = () if path == "/" else tuple(path[1:].split("/"))
    candidates = [
        item
        for item in snapshot.compiled.routes
        if len(item.segments) == len(segments)
        and all(
            a == b or (a.startswith("{") and a.endswith("}") and b != "")
            for a, b in zip(item.segments, segments)
        )
    ]
    matching = [item for item in candidates if method in item.route.methods]
    if matching:
        return max(matching, key=lambda item: item.literal_count).route, None
    if candidates:
        return None, (
            405,
            "METHOD_NOT_ALLOWED",
            {"Allow": ", ".join(sorted({m for item in candidates for m in item.route.methods}))},
        )
    if snapshot.compiled.document.service.unmatched_action == "deny":
        return None, (404, "ROUTE_NOT_FOUND", {})
    return None, None


def public_error(code, status, request_id, headers=None):
    return JSONResponse(
        {
            "error": {
                "code": code,
                "message": code.replace("_", " ").capitalize() + ".",
                "request_id": request_id,
            }
        },
        status_code=status,
        headers={"Cache-Control": "no-store", "X-Request-ID": request_id, **(headers or {})},
    )


class ObservedResponse(Response):
    def __init__(self, response, trace, sink, permit, upstream=None, deadline=None):
        super().__init__(status_code=response.status_code)
        self.response, self.trace, self.sink, self.permit = response, trace, sink, permit
        self.upstream, self.deadline = upstream, deadline

    async def __call__(self, scope, receive, send):
        async def observed_send(message):
            if message["type"] == "http.response.start":
                self.trace["status_code"] = message["status"]
            await send(message)

        try:
            async with asyncio.timeout_at(self.deadline):
                await self.response(scope, receive, observed_send)
        except (asyncio.CancelledError, ClientDisconnect):
            self.trace["decision"] = "client_disconnected"
            raise
        except Exception:
            self.trace["truncated"] = self.trace["status_code"] is not None
            self.trace["decision"] = "upstream_error" if self.upstream else "gateway_error"
            self.trace["reason_code"] = "STREAM_TERMINATED"
            raise RuntimeError("Response stream terminated") from None
        finally:
            try:
                if self.upstream:
                    await self.upstream.aclose()
            finally:
                self.permit.release()
                started = self.trace.pop("_started")
                self.trace["duration_ms"] = max(0, int((time.monotonic() - started) * 1000))
                self.trace["at_ms"] = int(time.time() * 1000)
                self.sink.enqueue(RequestEvent(**self.trace))


def create_gateway(
    settings: Settings | None = None,
    *,
    db=None,
    registry=None,
    rate_secret=None,
    transport=None,
    trusted_edge_cidrs=(),
    clock=None,
    runtime_lock=True,
):
    trusted = tuple(ipaddress.ip_network(value) for value in trusted_edge_cidrs)
    if any(network.prefixlen == 0 for network in trusted):
        raise ValueError("Blanket proxy trust is forbidden")
    now = clock or (lambda: int(time.time() * 1000))

    @asynccontextmanager
    async def lifespan(app):
        actual = settings or Settings.from_env()
        store_db = db or Database(actual.db_path)
        async with AsyncExitStack() as cleanup:
            if db is None:
                cleanup.push_async_callback(store_db.close)
            # Migration is explicit CLI work, never a race between server processes.
            async with store_db.read() as conn:
                await conn.execute("SELECT singleton FROM runtime_config")
            config = ConfigStore(store_db, registry or actual.load_registry(), clock=now)
            protection = ProtectionService(store_db, rate_secret or actual.load_rate_secret())
            lock = FileLock(str(actual.data_dir / "gateway.lock.runtime")) if runtime_lock else None
            if lock:
                lock.acquire(timeout=0)
                cleanup.callback(lock.release)
            forwarder = Forwarder(transport)
            cleanup.push_async_callback(forwarder.close)
            sink = EventSink(store_db)
            app.state.settings, app.state.db = actual, store_db
            app.state.config, app.state.protection = config, protection
            app.state.forwarder, app.state.sink = forwarder, sink
            app.state.permits = asyncio.Semaphore(50)
            app.state.inspections = asyncio.Semaphore(2)
            instance, started = str(uuid.uuid4()), now()
            await config.load_snapshot()
            await config.poll_and_apply()
            sink.start()
            cleanup.push_async_callback(sink.close)

            async def refresh():
                tick = 0
                while True:
                    try:
                        await config.poll_and_apply()
                        if tick % 10 == 0:
                            await config.heartbeat(instance, started, sink.dropped)
                    except Exception:
                        # Admission independently requires healthy security storage.
                        pass
                    tick += 1
                    await asyncio.sleep(0.5)

            refresher = asyncio.create_task(refresh())

            async def stop_refresh():
                refresher.cancel()
                await asyncio.gather(refresher, return_exceptions=True)

            cleanup.push_async_callback(stop_refresh)
            yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/_shield/health/live")
    async def live():
        return {"status": "live"}

    @app.get("/_shield/health/ready")
    async def ready():
        try:
            if app.state.config.snapshot is None:
                raise StorageUnavailable()
            async with app.state.db.write() as conn:
                await conn.execute("SELECT singleton FROM security_clock")
            return {"status": "ready"}
        except Exception:
            return JSONResponse({"status": "unready"}, status_code=503)

    @app.api_route("/{path:path}", methods=METHODS)
    async def handle(request: Request, path: str):
        request_id = str(uuid.uuid4())
        if request.url.path.startswith("/_shield/"):
            return public_error("ROUTE_NOT_FOUND", 404, request_id)
        permit = app.state.permits
        trace = dict(
            request_id=request_id,
            at_ms=now(),
            config_version=None,
            route_id=None,
            method=request.method,
            decision="blocked",
            reason_code="BAD_REQUEST",
            status_code=None,
            upstream_status=None,
            client_digest=None,
            duration_ms=0,
            request_bytes=0,
            response_bytes=0,
            origin_attempted=False,
            truncated=False,
            _started=time.monotonic(),
        )
        if permit.locked():
            trace.pop("_started")
            trace.update(decision="gateway_error", reason_code="GATEWAY_BUSY", status_code=503)
            app.state.sink.enqueue(RequestEvent(**trace))
            return public_error("GATEWAY_BUSY", 503, request_id, {"Retry-After": "1"})
        await permit.acquire()
        upstream = None

        def wrap(response, deadline=None):
            return ObservedResponse(response, trace, app.state.sink, permit, upstream, deadline)

        def fail(code, status, headers=None):
            trace["reason_code"] = code
            trace["decision"] = "gateway_error" if status >= 500 else "blocked"
            return wrap(public_error(code, status, request_id, headers))

        try:
            headers = list(request.scope["headers"])
            if len(headers) > 100 or sum(len(k) + len(v) for k, v in headers) > 32768:
                return fail("HEADERS_TOO_LARGE", 431)
            raw_path, query = request.scope.get("raw_path", b"/"), request.scope.get("query_string", b"")
            if len(raw_path) + len(query) > 8192:
                return fail("TARGET_TOO_LONG", 414)
            if request.method not in METHODS[:7]:
                return fail("METHOD_NOT_ALLOWED", 405, {"Allow": ", ".join(METHODS[:7])})
            if request.headers.get("upgrade"):
                return fail("BAD_REQUEST", 400)
            if connection_tokens(headers) & {b"authorization", b"cookie", b"host", b"x-shield-client-ip"}:
                return fail("BAD_REQUEST", 400)
            if any(
                sum(k.lower() == name for k, _ in headers) > 1
                for name in (
                    b"host",
                    b"authorization",
                    b"content-length",
                    b"content-type",
                    b"content-encoding",
                )
            ):
                return fail("BAD_REQUEST", 400)
            host, canonical = canonical_host(headers), canonical_path(raw_path)
            snapshot = app.state.config.snapshot
            if snapshot is None:
                return fail("CONFIG_UNAVAILABLE", 503)
            trace["config_version"] = snapshot.version
            service = snapshot.compiled.document.service
            if host != service.public_host:
                return fail("SERVICE_NOT_FOUND", 404)
            if not service.enabled:
                return fail("SERVICE_DISABLED", 503)
            ip = client_identity(request.client.host if request.client else "", headers, trusted)
            route, pending = select_route(snapshot, request.method, canonical)
            trace["route_id"] = route.id if route else None
            admission = await app.state.protection.admit(snapshot, route, ip, now(), request_id=request_id)
            trace["client_digest"] = admission.client_digest
            if not admission.allowed:
                extra = {"Retry-After": str(admission.retry_after)} if admission.retry_after else {}
                return fail(admission.code, admission.status, extra)
            if pending:
                return fail(pending[1], pending[0], pending[2])
            cap = min(service.max_body_bytes, route.max_body_bytes) if route else service.max_body_bytes
            if request.headers.get("content-encoding", "identity").lower() != "identity":
                return fail("CONTENT_ENCODING_NOT_SUPPORTED", 415)
            length = request.headers.get("content-length")
            if length is not None and (not length.isdecimal() or int(length) > cap):
                return fail(
                    "BODY_TOO_LARGE" if length.isdecimal() else "BAD_REQUEST",
                    413 if length.isdecimal() else 400,
                )
            body = bytearray()
            try:
                async with asyncio.timeout(10):
                    async for chunk in request.stream():
                        trace["request_bytes"] += len(chunk)
                        if trace["request_bytes"] > cap:
                            return fail("BODY_TOO_LARGE", 413)
                        body.extend(chunk)
            except TimeoutError:
                return fail("REQUEST_TIMEOUT", 408)
            if route:
                inspections = app.state.inspections
                if inspections.locked():
                    return fail("GATEWAY_BUSY", 503)
                await inspections.acquire()

                async def inspect():
                    try:
                        return await asyncio.to_thread(
                            validate_payload,
                            bytes(body),
                            route,
                            request.headers.get("content-type"),
                            request.headers.get("content-encoding"),
                        )
                    finally:
                        inspections.release()

                task = asyncio.create_task(inspect())
                violation = await asyncio.shield(task)
                if violation:
                    await app.state.protection.record_payload_rejection(
                        snapshot, ip, violation.code, request_id, now()
                    )
                    return fail(violation.code, violation.status)
            trace["origin_attempted"] = True
            deadline = asyncio.get_running_loop().time() + 30
            async with asyncio.timeout_at(deadline):
                upstream = await app.state.forwarder.forward(
                    PreparedRequest(
                        snapshot.compiled.upstream,
                        request.method,
                        raw_path,
                        query,
                        headers,
                        bytes(body),
                        service.public_host,
                        "https" if app.state.settings.mode == "production" else "http",
                        ip,
                        request_id,
                    )
                )
            trace["upstream_status"] = upstream.status_code
            no_body = request.method == "HEAD" or upstream.status_code in (204, 304)
            if (
                not no_body
                and upstream.headers.get("content-length", "").isdecimal()
                and int(upstream.headers["content-length"]) > 10485760
            ):
                await upstream.aclose()
                upstream = None
                return fail("UPSTREAM_RESPONSE_TOO_LARGE", 502)
            trace["decision"] = "upstream_error" if upstream.status_code >= 500 else "forwarded"
            trace["reason_code"] = "UPSTREAM_RESPONSE"

            async def content():
                if no_body:
                    return
                async for chunk in upstream.aiter_raw():
                    trace["response_bytes"] += len(chunk)
                    if trace["response_bytes"] > 10485760:
                        raise RuntimeError("Response exceeds configured limit")
                    yield chunk

            response = StreamingResponse(content(), status_code=upstream.status_code)
            response.raw_headers = response_headers(upstream.headers.raw, request_id)
            return wrap(response, deadline)
        except ProxyProblem as exc:
            return fail(exc.code, exc.status)
        except TimeoutError:
            return fail("UPSTREAM_TIMEOUT", 504)
        except ClientDisconnect:
            trace["decision"], trace["reason_code"] = "client_disconnected", "CLIENT_DISCONNECTED"
            return wrap(Response(status_code=400))
        except asyncio.CancelledError:
            try:
                if upstream:
                    await upstream.aclose()
            finally:
                permit.release()
                started = trace.pop("_started")
                trace.update(
                    decision="client_disconnected",
                    reason_code="CLIENT_DISCONNECTED",
                    duration_ms=max(0, int((time.monotonic() - started) * 1000)),
                )
                app.state.sink.enqueue(RequestEvent(**trace))
            raise
        except Exception:
            if upstream:
                await upstream.aclose()
                upstream = None
            return fail("PROTECTION_UNAVAILABLE", 503)

    return app
