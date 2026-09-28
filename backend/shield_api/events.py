"""Bounded metadata-only request events; critical events use DB transactions."""

from __future__ import annotations

import asyncio
import time

from .contracts import RequestEvent


class EventSink:
    def __init__(self, db):
        self.db = db
        self.queue: asyncio.Queue[RequestEvent] = asyncio.Queue(maxsize=1000)
        self.dropped = 0
        self._task = None

    def enqueue(self, event: RequestEvent) -> bool:
        try:
            self.queue.put_nowait(event)
            return True
        except asyncio.QueueFull:
            self.dropped += 1
            return False

    def start(self):
        self._task = asyncio.create_task(self._run())

    async def _run(self):
        tick = 0
        while True:
            await asyncio.sleep(0.25)
            await self.flush()
            if tick % 20 == 0:
                try:
                    await self.prune()
                except Exception:
                    pass  # Storage loss is surfaced by admission/readiness and queue drops.
            tick += 1

    async def prune(self):
        """Bounded retention runs even when there are no new request events."""
        async with self.db.write() as conn:
            for table in ("request_events", "security_events"):
                await conn.execute(
                    f"DELETE FROM {table} WHERE id IN (SELECT id FROM {table} "
                    "WHERE at_ms<? ORDER BY id LIMIT 500)",
                    (int(time.time() * 1000) - 7 * 86400000,),
                )
                await conn.execute(
                    f"DELETE FROM {table} WHERE id IN (SELECT id FROM {table} ORDER BY id LIMIT "
                    f"min(500,max(0,(SELECT count(*) FROM {table})-100000)))"
                )

    async def flush(self):
        batch = []
        for _ in range(100):
            try:
                batch.append(self.queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        if not batch:
            return
        fields = list(RequestEvent.model_fields)
        try:
            async with self.db.write() as conn:
                await conn.executemany(
                    f"INSERT INTO request_events ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})",
                    [tuple(event.model_dump()[field] for field in fields) for event in batch],
                )
                # Keep the row cap proportional to inserted batches even when
                # sustained traffic is faster than the idle maintenance timer.
                await conn.execute(
                    "DELETE FROM request_events WHERE id IN (SELECT id FROM request_events ORDER BY id LIMIT "
                    "min(500,max(0,(SELECT count(*) FROM request_events)-100000)))"
                )
        except asyncio.CancelledError:
            self.dropped += len(batch)
            raise
        except Exception:
            self.dropped += len(batch)
        finally:
            for _ in batch:
                self.queue.task_done()

    async def close(self):
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        try:
            async with asyncio.timeout(2):
                while not self.queue.empty():
                    await self.flush()
        except TimeoutError:
            self.dropped += self.queue.qsize()
