"""Local SQLite store and short, serialized transaction primitives."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import aiosqlite


class StorageUnavailable(RuntimeError):
    pass


class CapacityExceeded(StorageUnavailable):
    pass


CAPS = {
    "rate_counters": 100_000,
    "abuse_counters": 20_000,
    "bans": 10_000,
    "admin_sessions": 10_000,
    "admin_login_counters": 10_000,
}
EXPIRING_TABLES = frozenset({"rate_counters", "abuse_counters", "admin_sessions", "admin_login_counters"})


def wal_reset_fix_available(version: tuple[int, int, int] | None = None) -> bool:
    """Only run WAL on SQLite releases with the WAL-reset corruption fix."""
    current = version or sqlite3.sqlite_version_info
    return current >= (3, 51, 3) or (3, 50, 7) <= current < (3, 51, 0) or (3, 44, 6) <= current < (3, 45, 0)


class Database:
    def __init__(self, path: str | Path, *, writer_budget_ms: int = 100) -> None:
        self.path = Path(path)
        self.writer_budget_ms = writer_budget_ms
        self._write_lock = asyncio.Lock()
        self._writer_conn: aiosqlite.Connection | None = None
        self._connection_cleanups: set[asyncio.Task[None]] = set()

    def _track_cleanup(self, task: asyncio.Task[None]) -> None:
        self._connection_cleanups.add(task)
        task.add_done_callback(self._connection_cleanups.discard)

    async def _close_connection(self, connection: aiosqlite.Connection) -> None:
        closing = asyncio.create_task(connection.close())
        try:
            await asyncio.shield(closing)
        except asyncio.CancelledError:
            self._track_cleanup(closing)
            raise

    async def _dispose_after_connect(self, opening: asyncio.Task[aiosqlite.Connection]) -> None:
        try:
            connection = await opening
        except BaseException:
            return  # The opening task closes a partially configured connection.
        await connection.close()

    async def _connect(self) -> aiosqlite.Connection:
        if not wal_reset_fix_available():
            raise StorageUnavailable("SQLite version lacks required WAL fix")
        connection = aiosqlite.connect(self.path, isolation_level=None, timeout=self.writer_budget_ms / 1000)

        async def configure() -> aiosqlite.Connection:
            try:
                await connection
                connection.row_factory = aiosqlite.Row
                await connection.execute("PRAGMA foreign_keys=ON")
                await connection.execute(f"PRAGMA busy_timeout={self.writer_budget_ms}")
                return connection
            except BaseException:
                await connection.close()
                raise

        # aiosqlite starts a worker thread during its await. Let setup finish
        # after caller cancellation, then retire that connection in the background.
        opening = asyncio.create_task(configure())
        try:
            return await asyncio.shield(opening)
        except asyncio.CancelledError:
            self._track_cleanup(asyncio.create_task(self._dispose_after_connect(opening)))
            raise

    async def initialize(self) -> None:
        """Run numbered migrations once before serving either process."""
        if not wal_reset_fix_available():
            raise StorageUnavailable("SQLite version lacks required WAL fix")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with self._write_lock:
            conn = await self._connect()
            try:
                await conn.execute("PRAGMA journal_mode=WAL")
                await conn.execute("BEGIN EXCLUSIVE")
                await conn.execute(
                    "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, checksum TEXT NOT NULL, applied_at_ms INTEGER NOT NULL)"
                )
                migrations = sorted((Path(__file__).parent / "migrations").glob("[0-9][0-9][0-9]_*.sql"))
                for migration in migrations:
                    version = int(migration.name[:3])
                    source = migration.read_bytes()
                    checksum = hashlib.sha256(source).hexdigest()
                    row = await (
                        await conn.execute(
                            "SELECT checksum FROM schema_migrations WHERE version=?", (version,)
                        )
                    ).fetchone()
                    if row:
                        if row["checksum"] != checksum:
                            raise StorageUnavailable("Migration checksum mismatch")
                        continue
                    for statement in source.decode("utf-8").split(";"):
                        if statement.strip():
                            await conn.execute(statement)
                    await conn.execute(
                        "INSERT INTO schema_migrations(version,checksum,applied_at_ms) VALUES(?,?,?)",
                        (version, checksum, int(time.time() * 1000)),
                    )
                await conn.commit()
            except BaseException:
                await conn.rollback()
                raise
            finally:
                await self._close_connection(conn)

    async def close(self) -> None:
        async with self._write_lock:
            if self._writer_conn is not None:
                conn = self._writer_conn
                self._writer_conn = None
                await self._close_connection(conn)
        if self._connection_cleanups:
            await asyncio.gather(*tuple(self._connection_cleanups))

    @asynccontextmanager
    async def read(self) -> AsyncIterator[aiosqlite.Connection]:
        conn = await self._connect()
        try:
            yield conn
        finally:
            await self._close_connection(conn)

    @asynccontextmanager
    async def write(self) -> AsyncIterator[aiosqlite.Connection]:
        """Own the writer mutex through commit/rollback with a 100 ms total acquisition budget."""
        start = time.monotonic()
        try:
            await asyncio.wait_for(self._write_lock.acquire(), self.writer_budget_ms / 1000)
        except TimeoutError as exc:
            raise StorageUnavailable("Database writer busy") from exc
        conn = None
        try:
            remaining = self.writer_budget_ms / 1000 - (time.monotonic() - start)
            if remaining <= 0:
                raise StorageUnavailable("Database writer busy")
            if self._writer_conn is None:
                self._writer_conn = await asyncio.wait_for(self._connect(), remaining)
            conn = self._writer_conn
            remaining = self.writer_budget_ms / 1000 - (time.monotonic() - start)
            if remaining <= 0:
                raise StorageUnavailable("Database writer busy")
            # aiosqlite dispatches execute to a worker thread. A cancelled await
            # does not cancel the queued BEGIN, so retain the mutex until that
            # operation finishes and roll it back before another writer enters.
            begin = asyncio.create_task(conn.execute("BEGIN IMMEDIATE"))
            try:
                await asyncio.wait_for(asyncio.shield(begin), remaining)
            except BaseException:
                try:
                    await asyncio.shield(begin)
                except BaseException:
                    pass
                try:
                    await conn.rollback()
                finally:
                    self._writer_conn = None
                    await self._close_connection(conn)
                raise
            try:
                yield conn
                await conn.commit()
            except BaseException:
                await conn.rollback()
                raise
        except (aiosqlite.Error, TimeoutError) as exc:
            if self._writer_conn is not None:
                retiring = self._writer_conn
                self._writer_conn = None
                await self._close_connection(retiring)
            raise StorageUnavailable("Database writer unavailable") from exc
        finally:
            self._write_lock.release()


async def effective_now(conn: aiosqlite.Connection, system_now_ms: int) -> int:
    row = await (await conn.execute("SELECT last_seen_ms FROM security_clock WHERE singleton=1")).fetchone()
    if row is None:
        raise StorageUnavailable("Security clock missing")
    now_ms = max(system_now_ms, row["last_seen_ms"])
    await conn.execute("UPDATE security_clock SET last_seen_ms=? WHERE singleton=1", (now_ms,))
    return now_ms


async def read_effective_now(conn: aiosqlite.Connection, system_now_ms: int) -> int:
    row = await (await conn.execute("SELECT last_seen_ms FROM security_clock WHERE singleton=1")).fetchone()
    if row is None:
        raise StorageUnavailable("Security clock missing")
    return max(system_now_ms, row["last_seen_ms"])


async def insert_security_event(
    conn: aiosqlite.Connection,
    *,
    at_ms: int,
    actor_type: str,
    event_type: str,
    actor_id: str | None = None,
    service_id: str | None = None,
    client_digest: str | None = None,
    entity_id: str | None = None,
    request_id: str | None = None,
    safe_details: dict[str, object] | None = None,
) -> None:
    if actor_type not in ("system", "admin"):
        raise ValueError("Invalid security actor")
    details = json.dumps(safe_details or {}, sort_keys=True, separators=(",", ":"))
    if len(details.encode("utf-8")) > 4096:
        raise ValueError("Security details too large")
    await conn.execute(
        "INSERT INTO security_events(at_ms,actor_type,actor_id,event_type,service_id,client_digest,entity_id,request_id,safe_details_json) VALUES(?,?,?,?,?,?,?,?,?)",
        (at_ms, actor_type, actor_id, event_type, service_id, client_digest, entity_id, request_id, details),
    )
    await conn.execute(
        "DELETE FROM security_events WHERE id IN (SELECT id FROM security_events ORDER BY id LIMIT "
        "min(500,max(0,(SELECT count(*) FROM security_events)-100000)))"
    )


async def ensure_capacity(conn: aiosqlite.Connection, table: str, *, additional: int = 1) -> None:
    if table not in CAPS:
        raise ValueError("Unknown capacity table")
    count = (await (await conn.execute(f"SELECT count(*) AS n FROM {table}")).fetchone())["n"]
    if count + additional > CAPS[table]:
        raise CapacityExceeded(f"{table} capacity exceeded")


async def cleanup_expired(conn: aiosqlite.Connection, table: str, now_ms: int, *, batch: int = 500) -> int:
    if table not in EXPIRING_TABLES or not 1 <= batch <= 500:
        raise ValueError("Invalid cleanup request")
    cursor = await conn.execute(
        f"DELETE FROM {table} WHERE rowid IN (SELECT rowid FROM {table} WHERE expires_at_ms<=? LIMIT ?)",
        (now_ms, batch),
    )
    return cursor.rowcount
