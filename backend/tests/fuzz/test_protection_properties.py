"""Small generated reference-model sequences over isolated SQLite state."""

from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import given, settings, strategies as st

from shield_api.contracts import (
    AbuseConfig,
    AppliedConfig,
    CompiledConfig,
    Config,
    RateLimit,
    RegisteredUpstream,
    Service,
)
from shield_api.db import Database
from shield_api.protection import ProtectionService, client_digest, rate_settings_hash


def _snapshot(limit: int) -> AppliedConfig:
    service = Service(
        id="demo",
        name="Demo",
        public_host="example.test",
        upstream_id="origin",
        enabled=True,
        unmatched_action="baseline",
        max_body_bytes=1000,
        ip_rate=RateLimit(limit=limit, window_seconds=10),
        abuse=AbuseConfig(strike_limit=1000),
    )
    config = Config(schema_version=1, service=service)
    upstream = RegisteredUpstream(id="origin", name="Origin", scheme="http", host="localhost", port=9000)
    return AppliedConfig(version=1, compiled=CompiledConfig(document=config, upstream=upstream, routes=()))


@settings(max_examples=100, deadline=None)
@given(
    limit=st.integers(min_value=1, max_value=5),
    attempts=st.lists(
        st.tuples(st.sampled_from(("192.0.2.1", "192.0.2.2")), st.integers(min_value=0, max_value=35_000)),
        min_size=1,
        max_size=12,
    ),
)
def test_fixed_window_reference_model(limit, attempts):
    async def scenario(path: Path) -> None:
        # This property compares the algorithm with a reference model, not disk
        # scheduling. Default-budget fail-closed behavior is tested separately.
        db = Database(path, writer_budget_ms=5000)
        await db.initialize()
        try:
            protection = ProtectionService(db, b"s" * 32)
            snap = _snapshot(limit)
            clock = 0
            counters: dict[tuple[str, int], int] = {}
            for index, (ip, supplied_time) in enumerate(attempts):
                clock = max(clock, supplied_time)
                key = (ip, clock // 10_000)
                counters[key] = min(counters.get(key, 0) + 1, limit + 1)
                expected = counters[key] <= limit
                result = await protection.admit(snap, None, ip, supplied_time, str(index))
                assert result.allowed is expected
                assert result.code == (None if expected else "RATE_LIMITED")
                if not expected:
                    assert result.retry_after == (10_000 - clock % 10_000 + 999) // 1000
                assert result.client_digest == client_digest(b"s" * 32, ip)
        finally:
            await db.close()

    with TemporaryDirectory() as directory:
        asyncio.run(scenario(Path(directory) / "isolated.sqlite3"))


@settings(max_examples=100)
@given(limit=st.integers(min_value=1, max_value=100_000), seconds=st.integers(min_value=1, max_value=3600))
def test_hash_is_canonical_and_excludes_display_fields(limit, seconds):
    rate = RateLimit(limit=limit, window_seconds=seconds)
    assert rate_settings_hash(rate) == rate_settings_hash(RateLimit(limit=limit, window_seconds=seconds))
    assert len(rate_settings_hash(rate)) == 64
    assert client_digest(b"s" * 32, "::ffff:192.0.2.9") == client_digest(b"s" * 32, "192.0.2.9")
