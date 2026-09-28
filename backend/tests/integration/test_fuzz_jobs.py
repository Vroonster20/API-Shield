"""Exercise the real bounded worker and its durable coordinator state."""

from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path

import pytest
from filelock import FileLock

import shield_api.fuzz_jobs as fuzz_module
from shield_api.db import Database
from shield_api.fuzz_jobs import FuzzBusy, FuzzInvalid, FuzzJobs
from shield_api.fuzz_worker import Budget, MAX_STARTS


async def test_failure_before_worker_start_releases_queued_run(tmp_path, monkeypatch):
    db = Database(tmp_path / "live.sqlite3")
    await db.initialize()
    jobs = FuzzJobs(db, None)

    def fail_temp(*args, **kwargs):
        raise OSError("synthetic unavailable temp directory")

    monkeypatch.setattr(fuzz_module.tempfile, "mkdtemp", fail_temp)
    try:
        first = await jobs.start("core-demo-v1", 1, "operator")
        await jobs._task
        assert (await jobs.detail(first.run_id))["state"] == "error"
        second = await jobs.start("core-demo-v1", 2, "operator")
        await jobs._task
        assert second.run_id != first.run_id
        assert (await jobs.detail(second.run_id))["state"] == "error"
    finally:
        await jobs.close()
        await db.close()


@pytest.mark.asyncio
async def test_real_worker_isolated_from_live_database(tmp_path, monkeypatch):
    db = Database(tmp_path / "live.sqlite3")
    await db.initialize()
    jobs = FuzzJobs(db, None)
    created = []
    original_mkdtemp = fuzz_module.tempfile.mkdtemp

    def tracked_mkdtemp(*args, **kwargs):
        path = original_mkdtemp(*args, **kwargs)
        created.append(path)
        return path

    monkeypatch.setattr(fuzz_module.tempfile, "mkdtemp", tracked_mkdtemp)
    try:
        await jobs.startup()
        for profile, seed in (("other", 1), ("core-demo-v1", -1), ("core-demo-v1", True)):
            with pytest.raises(FuzzInvalid):
                await jobs.start(profile, seed, "operator")

        queued = await jobs.start("core-demo-v1", 42, "operator")
        with pytest.raises(FuzzBusy):
            await jobs.start("core-demo-v1", 43, "operator")
        await asyncio.wait_for(jobs._task, 30)
        detail = await jobs.detail(queued.run_id)
        assert detail is not None
        assert detail["state"] == "passed", detail
        assert (detail["passed_count"], detail["failed_count"], detail["error_count"]) == (17, 0, 0)
        assert detail["cases"][0]["case_id"] == "control-before"
        assert detail["cases"][-1]["case_id"] == "control-after"
        assert all(case["outcome"] == "passed" for case in detail["cases"])
        assert all(case["request_id"] for case in detail["cases"])
        assert sum(case["origin_receipt_delta"] for case in detail["cases"]) == 10
        report = {"state": "passed", "cases": detail["cases"]}
        assert jobs._valid_report(report)
        assert not jobs._valid_report({"state": "passed", "cases": detail["cases"][:-1]})
        tainted = [dict(case) for case in detail["cases"]]
        tainted[1]["actual"] = "secret from payload"
        assert not jobs._valid_report({"state": "passed", "cases": tainted})

        async with db.read() as conn:
            events = await (
                await conn.execute("SELECT event_type FROM security_events ORDER BY id")
            ).fetchall()
            assert [row["event_type"] for row in events] == ["fuzz.started", "fuzz.completed"]
            for table in ("config_revisions", "rate_counters", "abuse_counters", "bans", "request_events"):
                count = await (await conn.execute(f"SELECT count(*) AS n FROM {table}")).fetchone()
                assert count["n"] == 0, table
        assert (await jobs.list())["items"][0]["run_id"] == queued.run_id
        assert len(created) == 1 and not Path(created[0]).exists()
    finally:
        await jobs.close()
        await db.close()


@pytest.mark.asyncio
async def test_startup_interrupts_stale_run_without_replay(tmp_path):
    db = Database(tmp_path / "live.sqlite3")
    await db.initialize()
    try:
        async with db.write() as conn:
            await conn.execute(
                "INSERT INTO fuzz_runs(run_id,profile_id,seed,requested_by,state,created_at_ms) VALUES(?,?,?,?,?,?)",
                (
                    "00000000-0000-4000-8000-000000000001",
                    "core-demo-v1",
                    1,
                    "operator",
                    "running",
                    int(time.time() * 1000),
                ),
            )
        jobs = FuzzJobs(db, None)
        await jobs.startup()
        detail = await jobs.detail("00000000-0000-4000-8000-000000000001")
        assert detail["state"] == "interrupted"
        assert detail["error_count"] == 1
        assert detail["cases"] == []
        assert jobs._task is None
        await jobs.close()
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_shutdown_interrupts_active_worker_and_releases_slot(tmp_path):
    db = Database(tmp_path / "live.sqlite3")
    await db.initialize()
    jobs = FuzzJobs(db, None)
    try:
        queued = await jobs.start("core-demo-v1", 7, "operator")
        for _ in range(100):
            if jobs._process is not None:
                break
            await asyncio.sleep(0.02)
        assert jobs._process is not None
        process = jobs._process
        await asyncio.wait_for(jobs.close(), 5)
        assert process.returncode == 4  # Worker observed coordinator pipe EOF.
        assert (await jobs.detail(queued.run_id))["state"] == "interrupted"
        assert jobs._process is None
        next_jobs = FuzzJobs(db, None)
        await next_jobs.startup()
        assert (await next_jobs.list())["items"][0]["state"] == "interrupted"
        await next_jobs.close()
    finally:
        await jobs.close()
        await db.close()


@pytest.mark.asyncio
async def test_shared_request_budget_spaces_starts_and_caps_controls():
    budget = Budget()
    starts = []
    for _ in range(3):
        await budget.before()
        starts.append(time.monotonic())
    assert budget.starts == 3
    assert all(right - left >= 0.19 for left, right in zip(starts, starts[1:]))
    budget.starts = MAX_STARTS
    with pytest.raises(RuntimeError, match="budget"):
        await budget.before()


@pytest.mark.asyncio
async def test_cross_process_lock_fails_closed(tmp_path):
    db = Database(tmp_path / "live.sqlite3")
    await db.initialize()
    jobs = FuzzJobs(db, None)
    lock = FileLock(str(Path(tempfile.gettempdir()) / "shield-api-fuzz-worker.lock"))
    try:
        with lock:
            queued = await jobs.start("core-demo-v1", 8, "operator")
            await asyncio.wait_for(jobs._task, 10)
        detail = await jobs.detail(queued.run_id)
        assert detail["state"] == "error"
        assert detail["error_count"] == 1
        assert detail["cases"] == []
        assert jobs._process is None
    finally:
        await jobs.close()
        await db.close()


@pytest.mark.asyncio
async def test_retention_and_cursor_keep_active_runs(tmp_path):
    db = Database(tmp_path / "live.sqlite3")
    await db.initialize()
    now = int(time.time() * 1000)
    try:
        async with db.write() as conn:
            for index in range(60):
                state = "running" if index == 0 else "passed"
                await conn.execute(
                    "INSERT INTO fuzz_runs(run_id,profile_id,seed,requested_by,state,created_at_ms,finished_at_ms) VALUES(?,?,?,?,?,?,?)",
                    (
                        f"00000000-0000-4000-8000-{index:012d}",
                        "core-demo-v1",
                        index,
                        "operator",
                        state,
                        now - 60 + index,
                        None if index == 0 else now - 60 + index,
                    ),
                )
        jobs = FuzzJobs(db, None)
        async with db.write() as conn:
            await jobs._prune(conn, now)
        first = await jobs.list(limit=20)
        second = await jobs.list(cursor=first["next_cursor"], limit=20)
        third = await jobs.list(cursor=second["next_cursor"], limit=20)
        ids = [item["run_id"] for page in (first, second, third) for item in page["items"]]
        assert len(ids) == len(set(ids)) == 51
        assert "00000000-0000-4000-8000-000000000000" in ids
        assert third["next_cursor"] is None
        with pytest.raises(ValueError):
            await jobs.list(cursor="bad cursor")
        await jobs.close()
    finally:
        await db.close()
