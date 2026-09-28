"""Fault and state-boundary checks for gateway protection dependencies."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest

from shield_api.config import ConfigStore
from shield_api.contracts import (
    AbuseConfig,
    AppliedConfig,
    CompiledConfig,
    Config,
    RateLimit,
    RegisteredUpstream,
    Registry,
    Service,
)
from shield_api.db import Database, StorageUnavailable, wal_reset_fix_available
from shield_api.protection import ProtectionService

REGISTRY = Registry.model_validate(
    {"upstreams": [{"id": "origin", "name": "Origin", "scheme": "http", "host": "127.0.0.1", "port": 9000}]}
)


def config_doc():
    return {
        "schema_version": 1,
        "service": {
            "id": "demo",
            "name": "Demo",
            "public_host": "example.test",
            "upstream_id": "origin",
            "enabled": True,
            "unmatched_action": "baseline",
            "max_body_bytes": 1000,
            "ip_rate": {"limit": 2, "window_seconds": 60},
            "abuse": {},
            "routes": [],
        },
    }


def _snapshot(*, limit: int = 2, auto_ban: bool = False) -> AppliedConfig:
    service = Service(
        id="demo",
        name="Demo",
        public_host="example.test",
        upstream_id="origin",
        enabled=True,
        unmatched_action="baseline",
        max_body_bytes=1000,
        ip_rate=RateLimit(limit=limit, window_seconds=60),
        abuse=AbuseConfig(auto_ban_enabled=auto_ban, strike_limit=2, ban_seconds=30),
        routes=(),
    )
    upstream = RegisteredUpstream(id="origin", name="Origin", scheme="http", host="localhost", port=9000)
    return AppliedConfig(1, CompiledConfig(Config(schema_version=1, service=service), upstream, ()))


def test_wal_version_allowlist_boundaries():
    assert wal_reset_fix_available((3, 44, 6))
    assert not wal_reset_fix_available((3, 44, 5))
    assert not wal_reset_fix_available((3, 45, 0))
    assert wal_reset_fix_available((3, 50, 7))
    assert not wal_reset_fix_available((3, 51, 2))
    assert wal_reset_fix_available((3, 51, 3))
    assert wal_reset_fix_available((3, 53, 1))


@pytest.mark.asyncio
async def test_initialize_rejects_unfixed_sqlite_before_database_creation(tmp_path, monkeypatch):
    from shield_api import db as db_module

    monkeypatch.setattr(db_module, "wal_reset_fix_available", lambda: False)
    path = tmp_path / "store" / "shield.sqlite3"
    with pytest.raises(StorageUnavailable, match="WAL fix"):
        await Database(path).initialize()
    with pytest.raises(StorageUnavailable, match="WAL fix"):
        async with Database(path).read():
            pass
    assert not path.exists()


@pytest.mark.asyncio
async def test_cancelled_begin_retires_connection_before_next_writer(tmp_path):
    db = Database(tmp_path / "shield.sqlite3", writer_budget_ms=5000)
    await db.initialize()
    async with db.write():
        pass
    real = db._writer_conn
    started, release = asyncio.Event(), asyncio.Event()

    class DelayedBegin:
        def __getattr__(self, name):
            return getattr(real, name)

        async def execute(self, statement, *args):
            if statement == "BEGIN IMMEDIATE":
                started.set()
                await release.wait()
            return await real.execute(statement, *args)

    db._writer_conn = DelayedBegin()

    async def writer():
        async with db.write() as conn:
            await conn.execute("UPDATE security_clock SET last_seen_ms=123 WHERE singleton=1")

    task = asyncio.create_task(writer())
    await started.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert db._writer_conn is None
    async with db.write() as conn:
        await conn.execute("UPDATE security_clock SET last_seen_ms=456 WHERE singleton=1")
    async with db.read() as conn:
        row = await (
            await conn.execute("SELECT last_seen_ms FROM security_clock WHERE singleton=1")
        ).fetchone()
    assert row["last_seen_ms"] == 456
    await db.close()


@pytest.mark.asyncio
async def test_failed_applied_ack_does_not_publish_candidate_snapshot(tmp_path):
    db = Database(tmp_path / "shield.sqlite3")
    await db.initialize()
    store = ConfigStore(db, REGISTRY, clock=lambda: 1000)
    await store.apply_config(None, config_doc(), "admin")
    first = await store.poll_and_apply()
    changed = config_doc()
    changed["service"]["name"] = "New version"
    await store.apply_config(1, changed, "admin")

    class FailedCommit:
        read = db.read

        @asynccontextmanager
        async def write(self):
            async with db.write() as conn:
                yield conn
                raise RuntimeError("commit failed")

    store.db = FailedCommit()
    with pytest.raises(RuntimeError, match="commit failed"):
        await store.poll_and_apply()
    assert store.snapshot is first
    async with db.read() as conn:
        row = await (
            await conn.execute("SELECT applied_version FROM runtime_config WHERE singleton=1")
        ).fetchone()
    assert row["applied_version"] == 1
    store.db = db
    assert (await store.poll_and_apply()).version == 2
    await db.close()


@pytest.mark.asyncio
async def test_corrupt_applied_document_fails_closed_on_load(tmp_path):
    db = Database(tmp_path / "shield.sqlite3")
    await db.initialize()
    store = ConfigStore(db, REGISTRY, clock=lambda: 1000)
    await store.apply_config(None, config_doc(), "admin")
    await store.poll_and_apply()
    async with db.write() as conn:
        await conn.execute("UPDATE config_revisions SET document_json='{}' WHERE version=1")
    restarted = ConfigStore(db, REGISTRY, clock=lambda: 1000)
    with pytest.raises(StorageUnavailable, match="Applied configuration unavailable"):
        await restarted.load_snapshot()
    assert restarted.snapshot is None
    await db.close()


@pytest.mark.asyncio
async def test_unknown_routes_consume_baseline_and_ban_hits_preserve_ttl(tmp_path):
    db = Database(tmp_path / "shield.sqlite3")
    await db.initialize()
    protection = ProtectionService(db, b"k" * 32, "demo")
    snapshot = _snapshot(limit=2, auto_ban=True)
    ip = "192.0.2.55"
    assert (await protection.admit(snapshot, None, ip, 1000, "unknown-1")).allowed
    assert (await protection.admit(snapshot, None, ip, 1000, "unknown-2")).allowed
    assert (await protection.admit(snapshot, None, ip, 1000, "unknown-3")).code == "RATE_LIMITED"
    trigger = await protection.admit(snapshot, None, ip, 1000, "unknown-4")
    assert trigger.code == "RATE_LIMITED"
    async with db.read() as conn:
        ban = await (await conn.execute("SELECT ban_id,expires_at_ms FROM bans")).fetchone()
        counter = await (await conn.execute("SELECT route_id,count FROM rate_counters")).fetchone()
    assert counter["route_id"] == "" and counter["count"] == 3
    assert ban["expires_at_ms"] == 31_000
    for time_ms in (2000, 10_000, 30_000):
        assert (await protection.admit(snapshot, None, ip, time_ms, f"banned-{time_ms}")).code == "IP_BANNED"
    async with db.read() as conn:
        after = await (await conn.execute("SELECT ban_id,expires_at_ms FROM bans")).fetchone()
        count = await (await conn.execute("SELECT count FROM rate_counters")).fetchone()
    assert tuple(after) == tuple(ban)
    assert count["count"] == 3
    await db.close()
