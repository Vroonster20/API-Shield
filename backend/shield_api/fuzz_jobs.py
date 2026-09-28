"""One bounded, isolated synthetic fuzz job at a time."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
import sys
import tempfile
import time
import uuid
from pathlib import Path

from .contracts import FuzzSummary
from .db import Database, insert_security_event
from .settings import Settings

PROFILE = "core-demo-v1"
TERMINAL = ("passed", "failed", "error", "timed_out", "interrupted")
MAX_REPORT = 65_536
CASE_IDS = (
    "control-before",
    "signup-valid",
    "login-valid",
    "login-invalid-credentials",
    "cart-own",
    "cart-cross-user",
    "cart-unauthenticated",
    "path-block",
    "body-cap",
    "invalid-json",
    "schema-rejected",
    "rate-1",
    "rate-2",
    "rate-rejected-1",
    "rate-rejected-2",
    "temporary-ban",
    "control-after",
)
_STATUS = re.compile(r"status [1-5][0-9]{2}; origin receipts [0-9]{1,3}\Z")
_REQUEST_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")


class FuzzBusy(RuntimeError):
    pass


class FuzzInvalid(ValueError):
    pass


def _summary(row) -> dict[str, object]:
    return {
        key: row[key]
        for key in (
            "run_id",
            "profile_id",
            "seed",
            "state",
            "created_at_ms",
            "started_at_ms",
            "finished_at_ms",
            "passed_count",
            "failed_count",
            "error_count",
        )
    }


class FuzzJobs:
    def __init__(self, db: Database, settings: Settings) -> None:
        self.db, self.settings = db, settings
        self._task: asyncio.Task[None] | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._closing = False
        self._stop = asyncio.Event()

    async def startup(self) -> None:
        now = int(time.time() * 1000)
        async with self.db.write() as conn:
            rows = await (
                await conn.execute("SELECT run_id FROM fuzz_runs WHERE state IN ('queued','running')")
            ).fetchall()
            for row in rows:
                await conn.execute(
                    "UPDATE fuzz_runs SET state='interrupted',finished_at_ms=?,error_count=1 WHERE run_id=?",
                    (now, row["run_id"]),
                )
                await insert_security_event(
                    conn,
                    at_ms=now,
                    actor_type="system",
                    event_type="fuzz.interrupted",
                    entity_id=row["run_id"],
                )
            await self._prune(conn, now)

    async def start(self, profile_id: str, seed: int, admin_id: str) -> FuzzSummary:
        if profile_id != PROFILE or type(seed) is not int or not 0 <= seed <= 2_147_483_647:
            raise FuzzInvalid("Unsupported fuzz profile or seed")
        if self._closing:
            raise FuzzBusy("Fuzz runner is stopping")
        run_id, now = str(uuid.uuid4()), int(time.time() * 1000)
        async with self.db.write() as conn:
            active = await (
                await conn.execute("SELECT 1 FROM fuzz_runs WHERE state IN ('queued','running') LIMIT 1")
            ).fetchone()
            if active:
                raise FuzzBusy("A fuzz run is already active")
            await conn.execute(
                "INSERT INTO fuzz_runs(run_id,profile_id,seed,requested_by,state,created_at_ms) VALUES(?,?,?,?,?,?)",
                (run_id, PROFILE, seed, admin_id, "queued", now),
            )
        self._task = asyncio.create_task(self._run(run_id, seed), name=f"shield-fuzz-{run_id}")
        return FuzzSummary(
            run_id=run_id,
            profile_id=PROFILE,
            seed=seed,
            state="queued",
            created_at_ms=now,
            started_at_ms=None,
            finished_at_ms=None,
            passed_count=0,
            failed_count=0,
            error_count=0,
        )

    async def list(self, cursor: str | None = None, limit: int = 50) -> dict[str, object]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Invalid page limit")
        position = None
        if cursor:
            try:
                decoded = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
                if (
                    type(decoded) is not list
                    or len(decoded) != 2
                    or type(decoded[0]) is not int
                    or type(decoded[1]) is not str
                ):
                    raise ValueError()
                position = decoded
            except (ValueError, UnicodeError, TypeError):
                raise ValueError("Invalid page cursor") from None
        sql = "SELECT * FROM fuzz_runs"
        args: list[object] = []
        if position:
            sql += " WHERE (created_at_ms,run_id)<(?,?)"
            args.extend(position)
        sql += " ORDER BY created_at_ms DESC,run_id DESC LIMIT ?"
        args.append(limit + 1)
        async with self.db.read() as conn:
            rows = await (await conn.execute(sql, args)).fetchall()
        next_cursor = None
        if len(rows) > limit:
            last = rows[limit - 1]
            next_cursor = (
                base64.urlsafe_b64encode(
                    json.dumps([last["created_at_ms"], last["run_id"]], separators=(",", ":")).encode()
                )
                .decode()
                .rstrip("=")
            )
        return {"items": [_summary(row) for row in rows[:limit]], "next_cursor": next_cursor}

    async def detail(self, run_id: str) -> dict[str, object] | None:
        try:
            uuid.UUID(run_id)
        except ValueError:
            return None
        async with self.db.read() as conn:
            row = await (await conn.execute("SELECT * FROM fuzz_runs WHERE run_id=?", (run_id,))).fetchone()
        if row is None:
            return None
        result = _summary(row)
        report = json.loads(row["report_json"]) if row["report_json"] else {}
        result["cases"] = report.get("cases", [])
        return result

    async def close(self) -> None:
        self._closing = True
        self._stop.set()
        if self._task:
            await asyncio.gather(self._task, return_exceptions=True)

    async def _run(self, run_id: str, seed: int) -> None:
        temp: Path | None = None
        state = "error"
        report: dict[str, object] = {"cases": []}
        started = int(time.time() * 1000)
        deadline = asyncio.get_running_loop().time() + 60
        try:
            temp = Path(tempfile.mkdtemp(prefix="shield-fuzz-"))
            async with self.db.write() as conn:
                await conn.execute(
                    "UPDATE fuzz_runs SET state='running',started_at_ms=? WHERE run_id=?", (started, run_id)
                )
                await insert_security_event(
                    conn, at_ms=started, actor_type="system", event_type="fuzz.started", entity_id=run_id
                )
            if self._closing:
                state = "interrupted"
                return
            worker_env = {
                key: value
                for key, value in os.environ.items()
                if key.upper()
                in {
                    "PATH",
                    "SYSTEMROOT",
                    "WINDIR",
                    "TEMP",
                    "TMP",
                    "TMPDIR",
                    "HOME",
                    "USERPROFILE",
                    "LOCALAPPDATA",
                }
            }
            worker_env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent)
            self._process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "shield_api.fuzz_worker",
                run_id,
                str(seed),
                str(temp),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                env=worker_env,
            )
            wait_task = asyncio.create_task(self._process.wait())
            stop_task = asyncio.create_task(self._stop.wait())
            try:
                done, _ = await asyncio.wait(
                    {wait_task, stop_task},
                    timeout=max(0, deadline - asyncio.get_running_loop().time()),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if stop_task in done:
                    state = "interrupted"
                    if self._process.stdin:
                        self._process.stdin.close()
                    try:
                        await asyncio.wait_for(asyncio.shield(wait_task), 2)
                    except TimeoutError:
                        self._process.kill()
                        await wait_task
                elif wait_task not in done:
                    state = "timed_out"
                    self._process.kill()
                    await wait_task
                else:
                    path = temp / "report.json"
                    if self._process.returncode == 0 and path.is_file() and path.stat().st_size <= MAX_REPORT:
                        candidate = json.loads(path.read_text(encoding="utf-8"))
                        if self._valid_report(candidate):
                            report = candidate
                            state = candidate["state"]
                    if self._closing:
                        state = "interrupted"
            finally:
                stop_task.cancel()
                wait_task.cancel()
                await asyncio.gather(stop_task, wait_task, return_exceptions=True)
        except Exception:
            state = "interrupted" if self._closing else "error"
        finally:
            if self._process and self._process.returncode is None:
                self._process.kill()
                await self._process.wait()
            self._process = None
            if temp is not None:
                shutil.rmtree(temp, ignore_errors=True)
            await self._finish(run_id, state, report)

    @staticmethod
    def _valid_report(report: object) -> bool:
        if (
            not isinstance(report, dict)
            or set(report) != {"state", "cases"}
            or report["state"] not in ("passed", "failed", "error")
        ):
            return False
        cases = report.get("cases")
        if not isinstance(cases, list) or not 1 <= len(cases) <= len(CASE_IDS):
            return False
        required = {
            "case_id",
            "expected",
            "actual",
            "outcome",
            "request_id",
            "elapsed_ms",
            "origin_receipt_delta",
        }
        seen: set[str] = set()
        for case in cases:
            if not isinstance(case, dict) or set(case) != required:
                return False
            if any(
                type(case[key]) is not str or len(case[key]) > 256
                for key in ("case_id", "expected", "actual", "outcome")
            ):
                return False
            if case["case_id"] not in CASE_IDS or case["case_id"] in seen:
                return False
            seen.add(case["case_id"])
            if not _STATUS.fullmatch(case["expected"]) or not (
                _STATUS.fullmatch(case["actual"]) or case["actual"] == "request error"
            ):
                return False
            if (
                case["outcome"] not in ("passed", "failed", "error")
                or case["request_id"] is not None
                and (type(case["request_id"]) is not str or not _REQUEST_ID.fullmatch(case["request_id"]))
            ):
                return False
            if any(
                type(case[key]) is not int or not 0 <= case[key] <= 60_000
                for key in ("elapsed_ms", "origin_receipt_delta")
            ):
                return False
        if report["state"] == "passed" and (
            tuple(case["case_id"] for case in cases) != CASE_IDS
            or any(c["outcome"] != "passed" for c in cases)
        ):
            return False
        if report["state"] == "failed" and all(c["outcome"] == "passed" for c in cases):
            return False
        return len(json.dumps(report, separators=(",", ":")).encode()) <= MAX_REPORT

    async def _finish(self, run_id: str, state: str, report: dict[str, object]) -> None:
        cases = report.get("cases", [])
        if not isinstance(cases, list):
            cases = []
        passed = sum(c.get("outcome") == "passed" for c in cases if isinstance(c, dict))
        failed = sum(c.get("outcome") == "failed" for c in cases if isinstance(c, dict))
        errors = sum(c.get("outcome") == "error" for c in cases if isinstance(c, dict))
        if state in ("error", "timed_out", "interrupted") and errors == 0:
            errors = 1
        now = int(time.time() * 1000)
        encoded = json.dumps({"cases": cases}, separators=(",", ":"), ensure_ascii=True)
        if len(encoded.encode()) > MAX_REPORT:
            state, encoded, passed, failed, errors = "error", '{"cases":[]}', 0, 0, 1
        async with self.db.write() as conn:
            update = await conn.execute(
                "UPDATE fuzz_runs SET state=?,finished_at_ms=?,passed_count=?,failed_count=?,error_count=?,report_json=? WHERE run_id=? AND state IN ('queued','running')",
                (state, now, passed, failed, errors, encoded, run_id),
            )
            if update.rowcount != 1:
                return
            await insert_security_event(
                conn,
                at_ms=now,
                actor_type="system",
                event_type="fuzz.interrupted" if state == "interrupted" else "fuzz.completed",
                entity_id=run_id,
                safe_details={"state": state, "passed": passed, "failed": failed, "errors": errors},
            )
            await self._prune(conn, now)

    @staticmethod
    async def _prune(conn, now: int) -> None:
        await conn.execute(
            "DELETE FROM fuzz_runs WHERE state IN ('passed','failed','error','timed_out','interrupted') AND finished_at_ms<?",
            (now - 7 * 86_400_000,),
        )
        await conn.execute(
            "DELETE FROM fuzz_runs WHERE run_id IN (SELECT run_id FROM fuzz_runs WHERE state IN ('passed','failed','error','timed_out','interrupted') ORDER BY finished_at_ms DESC,run_id DESC LIMIT -1 OFFSET 50)"
        )
