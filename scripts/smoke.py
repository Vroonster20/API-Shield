"""Reproducible local-only 60 second / 20 concurrent gateway smoke check."""

import asyncio
import json
import platform
import sqlite3
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from fastapi import FastAPI  # noqa: E402
from tests.integration.test_gateway_network import gateway_for  # noqa: E402
from tests.network_support import serve  # noqa: E402


async def main():
    origin = FastAPI()
    receipts = 0

    @origin.get("/ping")
    async def ping():
        nonlocal receipts
        receipts += 1
        return {"ok": True}

    document = {
        "schema_version": 1,
        "service": {
            "id": "smoke",
            "name": "Smoke",
            "public_host": "api.localhost",
            "upstream_id": "demo-origin",
            "enabled": True,
            "unmatched_action": "baseline",
            "max_body_bytes": 1024,
            "ip_rate": {"limit": 100000, "window_seconds": 60},
            "abuse": {"auto_ban_enabled": False},
            "routes": [],
        },
    }
    durations, statuses = [], Counter()
    with tempfile.TemporaryDirectory(prefix="shield-smoke-") as directory:
        async with serve(origin) as (_, port):
            async with gateway_for(Path(directory), port, document, writer_budget_ms=100) as (client, app, _):
                start = time.monotonic()

                async def caller():
                    while time.monotonic() - start < 60:
                        before = time.monotonic()
                        try:
                            response = await client.get("/ping")
                            statuses[str(response.status_code)] += 1
                        except Exception:
                            statuses["transport_error"] += 1
                        durations.append((time.monotonic() - before) * 1000)

                await asyncio.gather(*(caller() for _ in range(20)))
                await app.state.sink.flush()
                elapsed = time.monotonic() - start
                durations.sort()
                result = {
                    "python": platform.python_version(),
                    "sqlite": sqlite3.sqlite_version,
                    "platform": platform.system(),
                    "concurrency": 20,
                    "elapsed_seconds": round(elapsed, 2),
                    "writer_budget_ms": 100,
                    "requests": len(durations),
                    "statuses": dict(statuses),
                    "origin_receipts": receipts,
                    "dropped_events": app.state.sink.dropped,
                    "permits_returned": app.state.permits._value == 50,
                    "latency_ms": {
                        name: round(durations[min(len(durations) - 1, int(len(durations) * fraction))], 2)
                        for name, fraction in (("p50", 0.5), ("p95", 0.95), ("p99", 0.99))
                    },
                }
                print(json.dumps(result, indent=2))
                if (
                    statuses.get("transport_error", 0)
                    or statuses.get("500", 0)
                    or receipts != statuses.get("200", 0)
                    or not result["permits_returned"]
                ):
                    raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
