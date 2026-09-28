"""Administrator password, login limit, and opaque session operations."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
import secrets
import time
import uuid
from dataclasses import dataclass
from typing import Callable

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError

from .db import (
    Database,
    cleanup_expired,
    effective_now,
    ensure_capacity,
    insert_security_event,
    read_effective_now,
)
from .protection import client_digest


USERNAME_RE = re.compile(r"[a-z0-9_.-]{3,64}\Z")
TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{43}\Z")
ABSOLUTE_MS = 8 * 60 * 60 * 1000
IDLE_MS = 30 * 60 * 1000
LOGIN_WINDOW_MS = 60_000


class AuthError(ValueError):
    def __init__(self, code: str, status: int) -> None:
        self.code = code
        self.status = status
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class SessionInfo:
    admin_id: str
    username: str
    csrf_token: str
    expires_at_ms: int
    token: str | None = None

    def public(self) -> dict[str, object]:
        return {
            "admin": {"id": self.admin_id, "username": self.username},
            "csrf_token": self.csrf_token,
            "expires_at_ms": self.expires_at_ms,
        }


class AuthService:
    def __init__(self, db: Database, rate_secret: bytes, *, clock: Callable[[], int] | None = None) -> None:
        self.db = db
        self.rate_secret = rate_secret
        self.clock = clock or (lambda: int(time.time() * 1000))
        self.hasher = PasswordHasher(time_cost=3, memory_cost=65_536, parallelism=1, hash_len=32, salt_len=16)
        self._dummy_hash: str | None = None
        self._hash_slots: asyncio.Queue[None] = asyncio.Queue(maxsize=2)
        self._hash_slots.put_nowait(None)
        self._hash_slots.put_nowait(None)

    async def _hash_job(self, func, *args):
        try:
            self._hash_slots.get_nowait()
        except asyncio.QueueEmpty as exc:
            raise AuthError("ADMIN_BUSY", 503) from exc

        async def run():
            try:
                return await asyncio.to_thread(func, *args)
            finally:
                self._hash_slots.put_nowait(None)

        task = asyncio.create_task(run())
        # The thread keeps hashing if the HTTP request goes away; its slot follows the work.
        task.add_done_callback(lambda finished: None if finished.cancelled() else finished.exception())
        return await asyncio.shield(task)

    @staticmethod
    def validate_credentials(username: str, password: str) -> None:
        if not USERNAME_RE.fullmatch(username) or not 12 <= len(password) <= 128:
            raise AuthError("BAD_REQUEST", 400)

    async def bootstrap_admin(self, username: str, password: str) -> str:
        self.validate_credentials(username, password)
        password_hash = await self._hash_job(self.hasher.hash, password)
        admin_id = str(uuid.uuid4())
        async with self.db.write() as conn:
            count = (await (await conn.execute("SELECT count(*) AS n FROM admins")).fetchone())["n"]
            if count:
                raise AuthError("ADMIN_ALREADY_CONFIGURED", 409)
            await conn.execute(
                "INSERT INTO admins(id,username,password_hash,created_at_ms) VALUES(?,?,?,?)",
                (admin_id, username, password_hash, self.clock()),
            )
        return admin_id

    async def reset_password(self, username: str, password: str) -> None:
        self.validate_credentials(username, password)
        password_hash = await self._hash_job(self.hasher.hash, password)
        async with self.db.write() as conn:
            now_ms = await effective_now(conn, self.clock())
            row = await (await conn.execute("SELECT id FROM admins WHERE username=?", (username,))).fetchone()
            if row is None:
                raise AuthError("ADMIN_NOT_FOUND", 404)
            await conn.execute("UPDATE admins SET password_hash=? WHERE id=?", (password_hash, row["id"]))
            await conn.execute(
                "UPDATE admin_sessions SET revoked_at_ms=? WHERE admin_id=? AND revoked_at_ms IS NULL",
                (now_ms, row["id"]),
            )

    async def _record_login_attempt(self, digest: str, now_ms: int) -> int:
        limited = False
        async with self.db.write() as conn:
            now_ms = await effective_now(conn, now_ms)
            window = (now_ms // LOGIN_WINDOW_MS) * LOGIN_WINDOW_MS
            await cleanup_expired(conn, "admin_login_counters", now_ms)
            for scope, key, limit in (("ip", digest, 10), ("global", "global", 100)):
                row = await (
                    await conn.execute(
                        "SELECT count FROM admin_login_counters WHERE scope=? AND client_digest_or_global=? AND window_start_ms=?",
                        (scope, key, window),
                    )
                ).fetchone()
                if row is None:
                    await ensure_capacity(conn, "admin_login_counters")
                    await conn.execute(
                        "INSERT INTO admin_login_counters(scope,client_digest_or_global,window_start_ms,count,expires_at_ms) VALUES(?,?,?,?,?)",
                        (scope, key, window, 1, window + LOGIN_WINDOW_MS),
                    )
                else:
                    await conn.execute(
                        "UPDATE admin_login_counters SET count=? WHERE scope=? AND client_digest_or_global=? AND window_start_ms=?",
                        (min(row["count"] + 1, limit + 1), scope, key, window),
                    )
                if row and row["count"] >= limit:
                    limited = True
        if limited:
            raise AuthError("ADMIN_BUSY", 503)
        return now_ms

    async def login(
        self, username: str, password: str, canonical_ip: str, prior_token: str | None = None
    ) -> SessionInfo:
        digest = client_digest(self.rate_secret, canonical_ip)
        now_ms = await self._record_login_attempt(digest, self.clock())
        self.validate_credentials(username, password)
        async with self.db.read() as conn:
            row = await (
                await conn.execute(
                    "SELECT id,username,password_hash FROM admins WHERE username=?", (username,)
                )
            ).fetchone()
        if self._dummy_hash is None:
            self._dummy_hash = await self._hash_job(self.hasher.hash, "invalid-admin-dummy-password")
        password_hash = row["password_hash"] if row else self._dummy_hash
        try:
            verified = await self._hash_job(self.hasher.verify, password_hash, password)
        except (VerifyMismatchError, VerificationError):
            verified = False
        if not row or not verified:
            async with self.db.write() as conn:
                await insert_security_event(
                    conn,
                    at_ms=now_ms,
                    actor_type="system",
                    event_type="admin.login_failed",
                    client_digest=digest,
                )
            raise AuthError("ADMIN_UNAUTHENTICATED", 401)
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
        csrf = secrets.token_urlsafe(32)
        expires = now_ms + ABSOLUTE_MS
        async with self.db.write() as conn:
            await cleanup_expired(conn, "admin_sessions", now_ms)
            await ensure_capacity(conn, "admin_sessions")
            if prior_token and TOKEN_RE.fullmatch(prior_token):
                prior_hash = hashlib.sha256(prior_token.encode("ascii")).hexdigest()
                await conn.execute(
                    "UPDATE admin_sessions SET revoked_at_ms=? WHERE token_hash=? AND revoked_at_ms IS NULL",
                    (now_ms, prior_hash),
                )
            await conn.execute(
                "INSERT INTO admin_sessions(token_hash,admin_id,csrf_token,created_at_ms,last_seen_ms,expires_at_ms) VALUES(?,?,?,?,?,?)",
                (token_hash, row["id"], csrf, now_ms, now_ms, expires),
            )
            await insert_security_event(
                conn,
                at_ms=now_ms,
                actor_type="admin",
                actor_id=row["id"],
                event_type="admin.login_succeeded",
                client_digest=digest,
            )
        return SessionInfo(row["id"], row["username"], csrf, expires, token)

    async def session(self, token: str | None) -> SessionInfo:
        if not token or not TOKEN_RE.fullmatch(token):
            raise AuthError("ADMIN_UNAUTHENTICATED", 401)
        token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
        now_ms = self.clock()
        async with self.db.read() as conn:
            row = await (
                await conn.execute(
                    "SELECT s.*,a.username FROM admin_sessions s JOIN admins a ON a.id=s.admin_id WHERE s.token_hash=?",
                    (token_hash,),
                )
            ).fetchone()
            now_ms = await read_effective_now(conn, now_ms)
        if (
            row is None
            or row["revoked_at_ms"] is not None
            or now_ms >= row["expires_at_ms"]
            or now_ms - row["last_seen_ms"] >= IDLE_MS
        ):
            raise AuthError("ADMIN_UNAUTHENTICATED", 401)
        if now_ms - row["last_seen_ms"] >= 60_000:
            async with self.db.write() as conn:
                now_ms = await effective_now(conn, self.clock())
                cursor = await conn.execute(
                    "UPDATE admin_sessions SET last_seen_ms=? WHERE token_hash=? AND revoked_at_ms IS NULL AND expires_at_ms>? AND last_seen_ms>?",
                    (now_ms, token_hash, now_ms, now_ms - IDLE_MS),
                )
                if cursor.rowcount != 1:
                    raise AuthError("ADMIN_UNAUTHENTICATED", 401)
        return SessionInfo(row["admin_id"], row["username"], row["csrf_token"], row["expires_at_ms"])

    async def logout(self, token: str, admin_id: str) -> None:
        if not TOKEN_RE.fullmatch(token):
            raise AuthError("ADMIN_UNAUTHENTICATED", 401)
        token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
        async with self.db.write() as conn:
            now_ms = await effective_now(conn, self.clock())
            await conn.execute(
                "UPDATE admin_sessions SET revoked_at_ms=? WHERE token_hash=? AND revoked_at_ms IS NULL",
                (now_ms, token_hash),
            )
            await insert_security_event(
                conn, at_ms=now_ms, actor_type="admin", actor_id=admin_id, event_type="admin.logout"
            )


def csrf_matches(expected: str, supplied: str | None) -> bool:
    return (
        supplied is not None
        and bool(TOKEN_RE.fullmatch(supplied))
        and hmac.compare_digest(expected, supplied)
    )
