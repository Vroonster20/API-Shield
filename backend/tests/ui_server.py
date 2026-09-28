"""Isolated real admin/gateway listeners for the Playwright smoke test."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shield_api.admin_api import create_management  # noqa: E402
from shield_api.admin_auth import AuthService  # noqa: E402
from shield_api.contracts import Registry  # noqa: E402
from shield_api.db import Database  # noqa: E402
from shield_api.gateway import create_gateway  # noqa: E402
from shield_api.settings import Settings  # noqa: E402


ADMIN_PORT = 18761
GATEWAY_PORT = 18762
USERNAME = "uismoke"
PASSWORD = "UiSmoke-password-2026"


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="shield-ui-smoke-") as temp:
        data_dir = Path(temp)
        registry_file = data_dir / "registry.json"
        secret_file = data_dir / "rate.key"
        registry_file.write_text(
            json.dumps(
                {
                    "upstreams": [
                        {
                            "id": "test-origin",
                            "name": "Test origin",
                            "scheme": "http",
                            "host": "127.0.0.1",
                            "port": 18763,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        secret = b"ui-smoke-isolated-rate-secret-00001"
        secret_file.write_bytes(secret)
        settings = Settings(
            data_dir=data_dir,
            registry_file=registry_file,
            admin_origin=f"http://127.0.0.1:{ADMIN_PORT}",
            mode="development",
            rate_secret_file=secret_file,
        )
        registry = Registry.model_validate_json(registry_file.read_text(encoding="utf-8"))
        db = Database(settings.db_path, writer_budget_ms=1000)
        await db.initialize()
        await AuthService(db, secret).bootstrap_admin(USERNAME, PASSWORD)
        admin = uvicorn.Server(
            uvicorn.Config(
                create_management(settings=settings, db=db, registry=registry),
                host="127.0.0.1",
                port=ADMIN_PORT,
                lifespan="on",
                log_level="warning",
                access_log=False,
                proxy_headers=False,
            )
        )
        gateway = uvicorn.Server(
            uvicorn.Config(
                create_gateway(
                    settings=settings, db=db, registry=registry, rate_secret=secret, runtime_lock=False
                ),
                host="127.0.0.1",
                port=GATEWAY_PORT,
                lifespan="on",
                log_level="warning",
                access_log=False,
                proxy_headers=False,
            )
        )
        tasks = [asyncio.create_task(server.serve()) for server in (admin, gateway)]
        try:
            # The browser test owns this isolated process and closes stdin at teardown.
            await asyncio.to_thread(sys.stdin.readline)
        finally:
            for server in (admin, gateway):
                server.should_exit = True
            await asyncio.gather(*tasks, return_exceptions=True)
            await db.close()


if __name__ == "__main__":
    asyncio.run(main())
