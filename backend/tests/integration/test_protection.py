from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

from shield_api.contracts import (
    AbuseConfig,
    AppliedConfig,
    CompiledConfig,
    Config,
    RateLimit,
    RegisteredUpstream,
    Route,
    Service,
)
from shield_api.db import Database
from shield_api.protection import BanError, ProtectionService, client_digest, rate_settings_hash


_OPEN_DATABASES = []


@pytest_asyncio.fixture(autouse=True)
async def close_databases():
    yield
    for db in _OPEN_DATABASES:
        await db.close()
    _OPEN_DATABASES.clear()


def snapshot(*, service_limit=10, route_limit=None, abuse=None, version=1, name="Demo"):
    route = Route(
        id="cart",
        name="Cart",
        path="/cart",
        methods=("POST",),
        max_body_bytes=1000,
        content_types=("application/json",),
        ip_rate=RateLimit(limit=route_limit, window_seconds=60) if route_limit else None,
    )
    service = Service(
        id="demo",
        name=name,
        public_host="example.test",
        upstream_id="origin",
        enabled=True,
        unmatched_action="baseline",
        max_body_bytes=1000,
        ip_rate=RateLimit(limit=service_limit, window_seconds=60),
        abuse=abuse or AbuseConfig(),
        routes=(route,),
    )
    config = Config(schema_version=1, service=service)
    upstream = RegisteredUpstream(id="origin", name="Origin", scheme="http", host="localhost", port=9000)
    return AppliedConfig(
        version=version, compiled=CompiledConfig(document=config, upstream=upstream, routes=())
    ), route


async def service_at(tmp_path, *, service_id="demo", writer_budget_ms=100):
    db = Database(tmp_path / "shield.sqlite3", writer_budget_ms=writer_budget_ms)
    await db.initialize()
    _OPEN_DATABASES.append(db)
    return ProtectionService(db, b"k" * 32, service_id), db


async def counts(db, table):
    async with db.read() as conn:
        return await (await conn.execute(f"SELECT * FROM {table}")).fetchall()


@pytest.mark.asyncio
async def test_concurrent_quota_and_saturation(tmp_path):
    protection, db = await service_at(tmp_path)
    snap, route = snapshot(service_limit=10)
    outcomes = await asyncio.gather(
        *(protection.admit(snap, route, "192.0.2.1", 120_000, str(i)) for i in range(50))
    )
    assert sum(item.allowed for item in outcomes) <= 10
    assert all(item.code in (None, "RATE_LIMITED", "PROTECTION_UNAVAILABLE") for item in outcomes)
    assert all(item.retry_after == 60 for item in outcomes if item.code == "RATE_LIMITED")
    rows = await counts(db, "rate_counters")
    assert len(rows) == 1 and rows[0]["count"] <= 11


@pytest.mark.asyncio
async def test_concurrent_quota_exact_with_uncontended_store(tmp_path):
    protection, db = await service_at(tmp_path, writer_budget_ms=5000)
    snap, route = snapshot(service_limit=10)
    outcomes = await asyncio.gather(
        *(protection.admit(snap, route, "192.0.2.1", 120_000, str(i)) for i in range(50))
    )
    assert sum(item.allowed for item in outcomes) == 10
    assert sum(item.code == "RATE_LIMITED" for item in outcomes) == 40
    assert (await counts(db, "rate_counters"))[0]["count"] == 11


@pytest.mark.asyncio
async def test_route_budget_retry_and_one_strike(tmp_path):
    protection, db = await service_at(tmp_path)
    snap, route = snapshot(service_limit=2, route_limit=1)
    assert (await protection.admit(snap, route, "192.0.2.1", 0, "a")).allowed
    second = await protection.admit(snap, route, "192.0.2.1", 1000, "b")
    assert second.code == "RATE_LIMITED" and second.retry_after == 59
    third = await protection.admit(snap, route, "192.0.2.1", 2000, "c")
    assert third.code == "RATE_LIMITED" and third.retry_after == 58
    rates = await counts(db, "rate_counters")
    assert {row["route_id"]: row["count"] for row in rates} == {"": 3, "cart": 2}
    abuse = await counts(db, "abuse_counters")
    assert len(abuse) == 1 and abuse[0]["count"] == 2


@pytest.mark.asyncio
async def test_detection_only_window_and_settings_reset(tmp_path):
    protection, db = await service_at(tmp_path)
    snap, _ = snapshot(service_limit=1, abuse=AbuseConfig(strike_limit=2))
    for i in range(5):
        await protection.admit(snap, None, "192.0.2.1", 1000, str(i))
    assert len(await counts(db, "bans")) == 0
    events = await counts(db, "security_events")
    assert [event["event_type"] for event in events] == ["abuse.threshold"]
    changed, _ = snapshot(service_limit=1, abuse=AbuseConfig(strike_limit=3), version=2)
    await protection.admit(changed, None, "192.0.2.1", 1000, "changed")
    assert len(await counts(db, "abuse_counters")) == 2


@pytest.mark.asyncio
async def test_automatic_ban_expiry_restart_and_no_quota_refund(tmp_path):
    protection, db = await service_at(tmp_path)
    abuse = AbuseConfig(auto_ban_enabled=True, strike_limit=2, ban_seconds=30)
    snap, route = snapshot(service_limit=1, abuse=abuse)
    assert (await protection.admit(snap, route, "192.0.2.1", 1000, "a")).allowed
    assert (await protection.admit(snap, route, "192.0.2.1", 1000, "b")).code == "RATE_LIMITED"
    trigger = await protection.admit(snap, route, "192.0.2.1", 1000, "c")
    assert trigger.code == "RATE_LIMITED"
    ban = (await counts(db, "bans"))[0]
    assert ban["expires_at_ms"] == 31_000
    blocked = await protection.admit(snap, route, "192.0.2.1", 2000, "d")
    assert blocked.code == "IP_BANNED" and blocked.retry_after == 29
    assert (await counts(db, "rate_counters"))[0]["count"] == 2
    restarted = ProtectionService(db, b"k" * 32, "demo")
    assert (await restarted.admit(snap, route, "192.0.2.1", 30_000, "e")).code == "IP_BANNED"
    # Equality expires the ban, but the original rate window remains exhausted.
    assert (await restarted.admit(snap, route, "192.0.2.1", 31_000, "f")).code == "RATE_LIMITED"
    assert (
        len([row for row in await counts(db, "security_events") if row["event_type"] == "ban.created"]) == 1
    )


@pytest.mark.asyncio
async def test_payload_strike_guard_rechecks_ban(tmp_path):
    protection, db = await service_at(tmp_path)
    snap, _ = snapshot(abuse=AbuseConfig(auto_ban_enabled=True, strike_limit=2))
    await protection.record_payload_rejection(snap, "192.0.2.1", "INVALID_JSON", "r1", 1000)
    await protection.record_payload_rejection(snap, "192.0.2.1", "SCHEMA_REJECTED", "r1", 1000)
    assert (await counts(db, "abuse_counters"))[0]["count"] == 1
    await protection.record_payload_rejection(snap, "192.0.2.1", "SCHEMA_REJECTED", "r2", 1000)
    ban = (await counts(db, "bans"))[0]
    await protection.record_payload_rejection(snap, "192.0.2.1", "INVALID_JSON", "r3", 2000)
    assert (await counts(db, "bans"))[0]["ban_id"] == ban["ban_id"]
    assert len(await counts(db, "abuse_counters")) == 0


@pytest.mark.asyncio
async def test_concurrent_threshold_creates_one_ban(tmp_path):
    protection, db = await service_at(tmp_path)
    snap, _ = snapshot(abuse=AbuseConfig(auto_ban_enabled=True, strike_limit=2))
    await asyncio.gather(
        *(
            protection.record_payload_rejection(snap, "192.0.2.12", "INVALID_JSON", str(i), 1000)
            for i in range(20)
        )
    )
    assert len(await counts(db, "bans")) == 1
    events = await counts(db, "security_events")
    assert [event["event_type"] for event in events] == ["abuse.threshold", "ban.created"]


@pytest.mark.asyncio
async def test_manual_ban_revoke_stale_and_digest_only(tmp_path):
    protection, db = await service_at(tmp_path)
    first = await protection.create_manual_ban(
        {"ip": "::ffff:192.0.2.8"}, 30, "operator_action", "admin", 1000
    )
    assert first.client_digest == client_digest(b"k" * 32, "192.0.2.8")
    assert first.source == "manual"
    with pytest.raises(BanError) as exc:
        await protection.create_manual_ban(
            {"client_digest": first.client_digest.upper()}, 60, "demo_test", "admin", 1001
        )
    assert exc.value.code == "BAN_ALREADY_ACTIVE"
    assert (await protection.revoke_ban(first.ban_id, "admin", 2000)).revoked
    assert not (await protection.revoke_ban(first.ban_id, "admin", 2001)).revoked
    second = await protection.create_manual_ban(
        {"client_digest": first.client_digest.upper()}, 30, "demo_test", "admin", 2002
    )
    assert second.ban_id != first.ban_id
    with pytest.raises(BanError) as exc:
        await protection.revoke_ban(first.ban_id, "admin", 2003)
    assert exc.value.code == "BAN_REPLACED"
    events = await counts(db, "security_events")
    assert [row["event_type"] for row in events] == ["ban.created", "ban.revoked", "ban.created"]
    assert "192.0.2.8" not in str([tuple(row) for row in events])


@pytest.mark.asyncio
async def test_manual_revoke_clears_strikes_without_refunding_rate(tmp_path):
    protection, db = await service_at(tmp_path)
    snap, route = snapshot(service_limit=1, abuse=AbuseConfig(strike_limit=3))
    await protection.admit(snap, route, "192.0.2.5", 1000, "a")
    assert (await protection.admit(snap, route, "192.0.2.5", 1000, "b")).code == "RATE_LIMITED"
    ban = await protection.create_manual_ban({"ip": "192.0.2.5"}, 30, "operator_action", "admin", 1000)
    assert (await protection.admit(snap, route, "192.0.2.5", 1000, "c")).code == "IP_BANNED"
    assert (await counts(db, "rate_counters"))[0]["count"] == 2
    await protection.revoke_ban(ban.ban_id, "admin", 1001)
    assert (await protection.admit(snap, route, "192.0.2.5", 1001, "d")).code == "RATE_LIMITED"
    assert (await counts(db, "abuse_counters"))[0]["count"] == 1
    assert [view.status for view in await protection.list_bans(1001, state="revoked")] == ["revoked"]


@pytest.mark.asyncio
async def test_nonqualifying_payload_errors_do_not_strike(tmp_path):
    protection, db = await service_at(tmp_path)
    snap, _ = snapshot()
    for index, code in enumerate(
        ("BODY_TOO_LARGE", "UNSUPPORTED_MEDIA_TYPE", "INSPECTION_LIMIT_EXCEEDED", "ORIGIN_ERROR")
    ):
        await protection.record_payload_rejection(snap, "192.0.2.6", code, str(index), 1000)
    assert await counts(db, "abuse_counters") == []


@pytest.mark.asyncio
async def test_durable_clock_and_stable_hash(tmp_path):
    protection, db = await service_at(tmp_path)
    snap, route = snapshot(service_limit=1)
    assert (await protection.admit(snap, route, "192.0.2.1", 61_000)).allowed
    assert (await protection.admit(snap, route, "192.0.2.1", 1)).code == "RATE_LIMITED"
    renamed, route2 = snapshot(service_limit=1, version=2, name="Renamed")
    assert (await protection.admit(renamed, route2, "192.0.2.1", 61_000)).code == "RATE_LIMITED"
    changed, route3 = snapshot(service_limit=2, version=3)
    assert (await protection.admit(changed, route3, "192.0.2.1", 61_000)).allowed
    assert rate_settings_hash(snap.compiled.document.service.ip_rate) != rate_settings_hash(
        changed.compiled.document.service.ip_rate
    )
