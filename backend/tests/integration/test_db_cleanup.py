"""Connection cancellation and security-event capacity regressions."""

from __future__ import annotations

import asyncio
import threading

import pytest

from shield_api import db as db_module
from shield_api.db import Database, StorageUnavailable, insert_security_event


async def assert_connection_closed(connection):
    # aiosqlite can resolve close() just before its worker returns. Join that
    # worker so this assertion checks eventual disposal without a timing guess.
    await asyncio.to_thread(connection._thread.join, 1)
    assert connection._connection is None
    assert not connection._thread.is_alive()


@pytest.mark.asyncio
async def test_write_timeout_during_sqlite_connect_closes_worker(tmp_path, monkeypatch):
    db = Database(tmp_path / "shield.sqlite3", writer_budget_ms=30)
    await db.initialize()
    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    connections = []
    real_connect = db_module.aiosqlite.connect

    def delayed_connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        connector = connection._connector

        def delayed_connector():
            raw = connector()
            loop.call_soon_threadsafe(started.set)
            release.wait(2)
            return raw

        connection._connector = delayed_connector
        connections.append(connection)
        return connection

    monkeypatch.setattr(db_module.aiosqlite, "connect", delayed_connect)

    async def write():
        async with db.write():
            pass

    task = asyncio.create_task(write())
    try:
        await asyncio.wait_for(started.wait(), 2)
        with pytest.raises(StorageUnavailable, match="writer unavailable"):
            await task
    finally:
        release.set()
    await db.close()
    assert len(connections) == 1
    await assert_connection_closed(connections[0])


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["initialize", "read", "write"])
async def test_cancel_during_connection_pragma_closes_worker(tmp_path, monkeypatch, operation):
    db = Database(tmp_path / "shield.sqlite3", writer_budget_ms=30)
    if operation != "initialize":
        await db.initialize()

    started = asyncio.Event()
    release = asyncio.Event()
    connections = []
    real_connect = db_module.aiosqlite.connect

    def delayed_connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        execute = connection.execute

        async def delayed_execute(statement, *params):
            if statement == "PRAGMA foreign_keys=ON":
                started.set()
                await release.wait()
            return await execute(statement, *params)

        connection.execute = delayed_execute
        connections.append(connection)
        return connection

    monkeypatch.setattr(db_module.aiosqlite, "connect", delayed_connect)

    async def run():
        if operation == "initialize":
            await db.initialize()
        elif operation == "read":
            async with db.read():
                pass
        else:
            async with db.write():
                pass

    task = asyncio.create_task(run())
    await asyncio.wait_for(started.wait(), 2)
    if operation == "write":
        with pytest.raises(StorageUnavailable, match="writer unavailable"):
            await task
    else:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert db._writer_conn is None
    release.set()
    await db.close()
    assert len(connections) == 1
    await assert_connection_closed(connections[0])

    monkeypatch.setattr(db_module.aiosqlite, "connect", real_connect)
    db.writer_budget_ms = 5000
    if operation == "initialize":
        await db.initialize()
    async with db.write() as conn:
        await conn.execute("UPDATE security_clock SET last_seen_ms=123 WHERE singleton=1")
    await db.close()


@pytest.mark.asyncio
async def test_security_events_prune_oldest_overflow_in_insert_transaction(tmp_path):
    db = Database(tmp_path / "shield.sqlite3", writer_budget_ms=5000)
    await db.initialize()
    async with db.write() as conn:
        await conn.execute(
            "WITH RECURSIVE seq(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM seq WHERE n<100001) "
            "INSERT INTO security_events(at_ms,actor_type,event_type,safe_details_json) "
            "SELECT n,'system','seed','{}' FROM seq"
        )
        await insert_security_event(conn, at_ms=100002, actor_type="system", event_type="new")
    async with db.read() as conn:
        row = await (
            await conn.execute(
                "SELECT count(*) AS n,min(id) AS oldest,max(id) AS newest FROM security_events"
            )
        ).fetchone()
    assert tuple(row) == (100_000, 3, 100_002)
    await db.close()
