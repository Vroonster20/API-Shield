import gzip
import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from starlette.responses import Response

from shield_api.config import ConfigStore
from shield_api.contracts import Registry
from shield_api.db import Database
from shield_api.demo import create_demo
from shield_api.gateway import create_gateway
from shield_api.settings import Settings
from tests.network_support import serve


@asynccontextmanager
async def gateway_for(tmp_path, origin_port, document=None, *, writer_budget_ms=1000):
    registry = Registry.model_validate(
        {
            "upstreams": [
                {
                    "id": "demo-origin",
                    "name": "Local test",
                    "scheme": "http",
                    "host": "127.0.0.1",
                    "port": origin_port,
                }
            ]
        }
    )
    db = Database(tmp_path / "shield.sqlite3", writer_budget_ms=writer_budget_ms)
    await db.initialize()
    settings = Settings(
        data_dir=tmp_path,
        registry_file=tmp_path / "registry.json",
        admin_origin="http://admin.localhost:8081",
        mode="development",
        rate_secret_file=tmp_path / "rate.key",
    )
    if document is None:
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
                "abuse": {"auto_ban_enabled": False},
                "routes": [],
            },
        }
    store = ConfigStore(db, registry)
    await store.apply_config(None, document, "test")
    app = create_gateway(settings, db=db, registry=registry, rate_secret=b"x" * 32, runtime_lock=False)
    try:
        async with serve(app) as (url, _):
            async with httpx.AsyncClient(
                base_url=url, headers={"Host": "api.localhost"}, trust_env=False, follow_redirects=False
            ) as client:
                yield client, app, db
    finally:
        await db.close()


async def test_network_bytes_headers_cookies_redirects_and_no_body(tmp_path):
    origin = FastAPI()
    seen = []
    compressed = gzip.compress(b"binary\x00content")

    @origin.api_route("/{path:path}", methods=["GET", "HEAD", "POST", "OPTIONS"])
    async def reply(request: Request, path: str):
        seen.append(
            (
                request.scope["raw_path"],
                request.scope["query_string"],
                list(request.scope["headers"]),
                await request.body(),
            )
        )
        if path == "cookies":
            result = Response("cookies")
            result.raw_headers.extend(
                [(b"set-cookie", b"first=one; Path=/"), (b"set-cookie", b"second=two; Path=/")]
            )
            return result
        if path == "redirect":
            return Response(status_code=307, headers={"Location": "/cookies"})
        if path == "gzip":
            return Response(compressed, headers={"Content-Encoding": "gzip"})
        if path == "head":
            return Response(b"", headers={"Content-Length": "123"})
        if path == "empty":
            return Response(status_code=204)
        if path == "cached":
            return Response(status_code=304, headers={"ETag": '"v1"'})
        return Response(
            b"\x00\xffresult",
            status_code=201,
            headers={"Access-Control-Allow-Origin": "https://example.test"},
        )

    async with serve(origin) as (_, port):
        async with gateway_for(tmp_path, port) as (client, app, db):
            raw = b'{ "token" : "secret-marker-body", "x": 1 }'
            response = await client.post(
                "/echo%20value?a=1&a=2&x=%2f",
                content=raw,
                headers={
                    "Authorization": "Bearer secret-marker-auth",
                    "Cookie": "app_session=secret-marker-cookie; shield_dev_session=admin-secret",
                    "X-Forwarded-For": "spoofed",
                    "X-User-Role": "admin",
                },
            )
            assert response.status_code == 201 and response.content == b"\x00\xffresult"
            assert response.headers["access-control-allow-origin"] == "https://example.test"
            path, query, headers, body = seen[-1]
            hdr = dict(headers)
            assert path == b"/echo%20value" and query == b"a=1&a=2&x=%2f" and body == raw
            assert hdr[b"authorization"] == b"Bearer secret-marker-auth"
            assert hdr[b"cookie"] == b"app_session=secret-marker-cookie"
            assert hdr[b"x-forwarded-for"] == b"127.0.0.1" and b"x-user-role" not in hdr
            assert hdr[b"host"] == f"127.0.0.1:{port}".encode()
            assert hdr[b"x-request-id"].decode() == response.headers["x-request-id"]
            cookies = await client.get("/cookies")
            assert len(cookies.headers.get_list("set-cookie")) == 2
            # A different caller must not inherit cookies stored by the shared proxy client.
            client.cookies.clear()
            await client.get("/echo")
            assert b"cookie" not in dict(seen[-1][2])
            before = len(seen)
            redirect = await client.get("/redirect")
            assert redirect.status_code == 307 and len(seen) == before + 1
            async with client.stream("GET", "/gzip") as response:
                wire = b"".join([part async for part in response.aiter_raw()])
            assert wire == compressed
            head = await client.head("/head")
            assert head.status_code == 200 and head.content == b"" and head.headers["content-length"] == "123"
            assert (await client.get("/empty")).status_code == 204
            assert (await client.get("/cached")).status_code == 304
            before = len(seen)
            blocked = await client.post("/echo", content=b"x" * 1025)
            assert blocked.status_code == 413 and len(seen) == before
            hidden = await client.get("/_shield/admin/v1/config")
            assert hidden.status_code == 404 and len(seen) == before
            await app.state.sink.flush()
            async with db.read() as conn:
                events = await (await conn.execute("SELECT * FROM request_events")).fetchall()
            serialized = str([dict(row) for row in events])
            assert "secret-marker" not in serialized and "admin-secret" not in serialized
            assert any(row["status_code"] == 413 and not row["origin_attempted"] for row in events)


async def test_signup_login_cart_ownership_and_config_only_booking(tmp_path):
    document = json.loads(
        (Path(__file__).parents[3] / "docs/shield-api/examples/storefront.snapshot.json").read_text()
    )
    # Separate application database: Shield has no access to user/password/cart tables.
    origin = create_demo(tmp_path / "application.sqlite3")
    async with serve(origin) as (_, port):
        async with gateway_for(tmp_path, port, document) as (client, _, db):
            alice = {"username": "alice", "password": "synthetic-alice-password"}
            bob = {"username": "bob", "password": "synthetic-bob-password"}
            assert (await client.post("/auth/register", json=alice)).status_code == 201
            assert (await client.post("/auth/register", json=bob)).status_code == 201
            assert (await client.post("/auth/login", json=alice)).status_code == 200
            item = await client.post("/cart/items", json={"product_id": "notebook", "quantity": 2})
            assert item.status_code == 201 and item.json()["total_cents"] == 1000
            before = origin.state.receipts
            invalid = await client.post(
                "/cart/items", json={"product_id": "notebook", "quantity": 0, "price_cents": 1}
            )
            assert invalid.status_code == 400 and origin.state.receipts == before
            assert (await client.post("/auth/login", json=bob)).status_code == 200
            assert (await client.delete("/cart/items/" + item.json()["id"])).status_code == 404
            assert (await client.get("/cart/items")).json()["items"] == []
            assert (
                await client.post("/reservations", json={"resource": "workshop", "seats": 2})
            ).status_code == 201
            async with db.read() as conn:
                names = {
                    row[0]
                    for row in await (
                        await conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                    ).fetchall()
                }
            assert "users" not in names and "cart" not in names
