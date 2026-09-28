import time

from shield_api.contracts import RequestEvent
from shield_api.db import Database, insert_security_event
from shield_api.events import EventSink


def event():
    return RequestEvent(
        request_id="fixture",
        at_ms=int(time.time() * 1000),
        config_version=1,
        route_id="login-post",
        method="POST",
        decision="blocked",
        reason_code="INVALID_JSON",
        status_code=400,
        upstream_status=None,
        client_digest="a" * 64,
        duration_ms=1,
        request_bytes=1,
        response_bytes=0,
        origin_attempted=False,
        truncated=False,
    )


async def test_queue_drop_and_idle_security_retention(tmp_path):
    db = Database(tmp_path / "events.sqlite3")
    await db.initialize()
    try:
        sink = EventSink(db)
        for _ in range(1000):
            assert sink.enqueue(event())
        assert not sink.enqueue(event()) and sink.dropped == 1
        await sink.flush()
        assert sink.queue.qsize() == 900
        async with db.write() as conn:
            await insert_security_event(conn, at_ms=1, actor_type="system", event_type="test.expired")
            await insert_security_event(
                conn, at_ms=int(time.time() * 1000), actor_type="system", event_type="test.current"
            )
        await sink.prune()
        async with db.read() as conn:
            rows = await (await conn.execute("SELECT event_type FROM security_events")).fetchall()
        assert [row[0] for row in rows] == ["test.current"]
        await sink.close()
        assert sink.queue.empty()
    finally:
        await db.close()
