import pytest

from shield_api.db import Database, effective_now, insert_security_event


@pytest.mark.asyncio
async def test_migration_clock_atomic_rollback(tmp_path):
    db = Database(tmp_path / "shield.sqlite3")
    await db.initialize()
    await db.initialize()
    async with db.write() as conn:
        assert await effective_now(conn, 2000) == 2000
        assert await effective_now(conn, 1500) == 2000
    with pytest.raises(RuntimeError):
        async with db.write() as conn:
            await insert_security_event(conn, at_ms=2000, actor_type="system", event_type="test")
            raise RuntimeError("rollback")
    async with db.read() as conn:
        row = await (await conn.execute("SELECT count(*) AS n FROM security_events")).fetchone()
        assert row["n"] == 0
        tables = {
            row["name"]
            for row in await (
                await conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()
        }
        assert {"rate_counters", "abuse_counters", "bans", "fuzz_runs", "runtime_config"} <= tables
    await db.close()
