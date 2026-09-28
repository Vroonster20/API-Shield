"""Persistent fixed-window admission, abuse strikes, and temporary bans."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import math
import re
import uuid
from collections import deque
from collections.abc import Mapping

from .contracts import Admission, AppliedConfig, BanView, CompiledRoute, RateLimit, RevokeResult, Route
from .db import (
    CapacityExceeded,
    Database,
    StorageUnavailable,
    cleanup_expired,
    effective_now,
    ensure_capacity,
    insert_security_event,
    read_effective_now,
)

_DIGEST_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_SIGNAL_CODES = frozenset({"INVALID_JSON", "SCHEMA_REJECTED"})


class BanError(ValueError):
    def __init__(self, code: str, status: int) -> None:
        self.code = code
        self.status = status
        super().__init__(code)


def canonical_ip(value: str) -> str:
    address = ipaddress.ip_address(value)
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return str(address.ipv4_mapped)
    return str(address)


def client_digest(secret: bytes, ip: str) -> str:
    if len(secret) < 32:
        raise ValueError("Rate secret must be at least 32 bytes")
    return hmac.new(secret, canonical_ip(ip).encode("ascii"), hashlib.sha256).hexdigest()


def rate_settings_hash(rate: RateLimit) -> str:
    document = {"algorithm": "fixed_window_v1", "limit": rate.limit, "window_seconds": rate.window_seconds}
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def abuse_settings_hash(abuse: object) -> str:
    document = {
        key: getattr(abuse, key)
        for key in ("auto_ban_enabled", "strike_limit", "window_seconds", "ban_seconds")
    }
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _ban_view(row: object, now_ms: int) -> BanView:
    revoked = row["revoked_at_ms"]
    status = "revoked" if revoked is not None else "expired" if now_ms >= row["expires_at_ms"] else "active"
    return BanView(
        ban_id=row["ban_id"],
        client_digest=row["client_digest"],
        source=row["source"],
        created_at_ms=row["created_at_ms"],
        expires_at_ms=row["expires_at_ms"],
        revoked_at_ms=revoked,
        status=status,
        reason_code=row["reason_code"],
    )


# Admin pagination reads the same row shape without duplicating status rules.
ban_view = _ban_view


def _active(row: object | None, now_ms: int) -> bool:
    return bool(row and row["revoked_at_ms"] is None and now_ms < row["expires_at_ms"])


class ProtectionService:
    def __init__(self, db: Database, rate_secret: bytes, service_id: str | None = None) -> None:
        if len(rate_secret) < 32:
            raise ValueError("Rate secret must be at least 32 bytes")
        self.db = db
        self.rate_secret = rate_secret
        self.service_id = service_id
        self._request_guard = asyncio.Lock()
        self._struck: set[str] = set()
        self._struck_order: deque[str] = deque()

    def digest(self, ip: str) -> str:
        return client_digest(self.rate_secret, ip)

    def _remember_strike(self, request_id: str | None) -> None:
        if request_id is None or request_id in self._struck:
            return
        self._struck.add(request_id)
        self._struck_order.append(request_id)
        if len(self._struck_order) > 10_000:
            self._struck.discard(self._struck_order.popleft())

    async def _ban_row(self, conn: object, service_id: str, digest: str) -> object | None:
        return await (
            await conn.execute(
                "SELECT * FROM bans WHERE service_id=? AND client_digest=?", (service_id, digest)
            )
        ).fetchone()

    async def _consume_rate(
        self, conn: object, service_id: str, route_id: str, rate: RateLimit, digest: str, now_ms: int
    ) -> int:
        period = rate.window_seconds * 1000
        start = (now_ms // period) * period
        key = (service_id, route_id, rate_settings_hash(rate), digest, start)
        row = await (
            await conn.execute(
                "SELECT count FROM rate_counters WHERE service_id=? AND route_id=? AND settings_hash=? AND client_digest=? AND window_start_ms=?",
                key,
            )
        ).fetchone()
        if row is None:
            await ensure_capacity(conn, "rate_counters")
            count = 1
            await conn.execute(
                "INSERT INTO rate_counters(service_id,route_id,settings_hash,client_digest,window_start_ms,count,expires_at_ms) VALUES(?,?,?,?,?,?,?)",
                (*key, count, start + period),
            )
        else:
            count = min(row["count"] + 1, rate.limit + 1)
            await conn.execute(
                "UPDATE rate_counters SET count=? WHERE service_id=? AND route_id=? AND settings_hash=? AND client_digest=? AND window_start_ms=?",
                (count, *key),
            )
        return math.ceil((start + period - now_ms) / 1000) if count > rate.limit else 0

    async def _strike(
        self, conn: object, service: object, digest: str, request_id: str | None, now_ms: int
    ) -> None:
        abuse = service.abuse
        period = abuse.window_seconds * 1000
        start = (now_ms // period) * period
        key = (service.id, digest, abuse_settings_hash(abuse), start)
        row = await (
            await conn.execute(
                "SELECT count,threshold_recorded FROM abuse_counters WHERE service_id=? AND client_digest=? AND settings_hash=? AND window_start_ms=?",
                key,
            )
        ).fetchone()
        if row is None:
            await ensure_capacity(conn, "abuse_counters")
            count, recorded = 1, 0
            await conn.execute(
                "INSERT INTO abuse_counters(service_id,client_digest,settings_hash,window_start_ms,count,threshold_recorded,expires_at_ms) VALUES(?,?,?,?,?,?,?)",
                (*key, count, recorded, start + period),
            )
        else:
            count = min(row["count"] + 1, abuse.strike_limit)
            recorded = row["threshold_recorded"]
            await conn.execute(
                "UPDATE abuse_counters SET count=? WHERE service_id=? AND client_digest=? AND settings_hash=? AND window_start_ms=?",
                (count, *key),
            )
        if count < abuse.strike_limit or recorded:
            return
        await conn.execute(
            "UPDATE abuse_counters SET threshold_recorded=1 WHERE service_id=? AND client_digest=? AND settings_hash=? AND window_start_ms=?",
            key,
        )
        await insert_security_event(
            conn,
            at_ms=now_ms,
            actor_type="system",
            event_type="abuse.threshold",
            service_id=service.id,
            client_digest=digest,
            request_id=request_id,
            safe_details={"strike_limit": abuse.strike_limit, "auto_ban_enabled": abuse.auto_ban_enabled},
        )
        if abuse.auto_ban_enabled:
            await self._create_ban(
                conn,
                service.id,
                digest,
                abuse.ban_seconds,
                "automatic",
                "abuse_threshold",
                now_ms,
                actor_type="system",
                actor_id=None,
                request_id=request_id,
            )

    async def _create_ban(
        self,
        conn: object,
        service_id: str,
        digest: str,
        duration_seconds: int,
        source: str,
        reason: str,
        now_ms: int,
        *,
        actor_type: str,
        actor_id: str | None,
        request_id: str | None = None,
    ) -> BanView:
        current = await self._ban_row(conn, service_id, digest)
        if _active(current, now_ms):
            raise BanError("BAN_ALREADY_ACTIVE", 409)
        if current is None:
            try:
                await ensure_capacity(conn, "bans")
            except CapacityExceeded:
                # Retain recent inactive rows for management until space is needed.
                # Their immutable creation/revoke history lives in security_events.
                await conn.execute(
                    "DELETE FROM bans WHERE rowid IN (SELECT rowid FROM bans "
                    "WHERE revoked_at_ms IS NOT NULL OR expires_at_ms<=? "
                    "ORDER BY created_at_ms LIMIT 500)",
                    (now_ms,),
                )
                await ensure_capacity(conn, "bans")
        ban_id = str(uuid.uuid4())
        expires = now_ms + duration_seconds * 1000
        await conn.execute(
            "INSERT INTO bans(service_id,client_digest,ban_id,source,created_at_ms,expires_at_ms,revoked_at_ms,reason_code) VALUES(?,?,?,?,?,?,NULL,?) "
            "ON CONFLICT(service_id,client_digest) DO UPDATE SET ban_id=excluded.ban_id,source=excluded.source,created_at_ms=excluded.created_at_ms,expires_at_ms=excluded.expires_at_ms,revoked_at_ms=NULL,reason_code=excluded.reason_code",
            (service_id, digest, ban_id, source, now_ms, expires, reason),
        )
        await conn.execute(
            "DELETE FROM abuse_counters WHERE service_id=? AND client_digest=?", (service_id, digest)
        )
        await insert_security_event(
            conn,
            at_ms=now_ms,
            actor_type=actor_type,
            actor_id=actor_id,
            event_type="ban.created",
            service_id=service_id,
            client_digest=digest,
            entity_id=ban_id,
            request_id=request_id,
            safe_details={"source": source, "reason_code": reason, "duration_seconds": duration_seconds},
        )
        return BanView(
            ban_id=ban_id,
            client_digest=digest,
            source=source,
            created_at_ms=now_ms,
            expires_at_ms=expires,
            revoked_at_ms=None,
            status="active",
            reason_code=reason,
        )

    async def admit(
        self,
        snapshot: AppliedConfig,
        route_or_pending_error: CompiledRoute | Route | None,
        canonical_ip: str,
        now_ms: int,
        request_id: str | None = None,
    ) -> Admission:
        service = snapshot.compiled.document.service
        digest = self.digest(canonical_ip)
        route = (
            route_or_pending_error.route
            if isinstance(route_or_pending_error, CompiledRoute)
            else route_or_pending_error
        )
        # The guard is local to this service instance; the database transaction owns
        # cross-request correctness and all durable state.
        try:
            async with self.db.write() as conn:
                now = await effective_now(conn, now_ms)
                ban = await self._ban_row(conn, service.id, digest)
                if _active(ban, now):
                    remaining = math.ceil((ban["expires_at_ms"] - now) / 1000)
                    return Admission(
                        allowed=False,
                        code="IP_BANNED",
                        status=403,
                        retry_after=max(1, remaining),
                        client_digest=digest,
                    )
                await cleanup_expired(conn, "rate_counters", now)
                await cleanup_expired(conn, "abuse_counters", now)
                retries = [await self._consume_rate(conn, service.id, "", service.ip_rate, digest, now)]
                if isinstance(route, Route) and route.ip_rate is not None:
                    retries.append(
                        await self._consume_rate(conn, service.id, route.id, route.ip_rate, digest, now)
                    )
                retry = max(retries)
                if retry:
                    await self._strike(conn, service, digest, request_id, now)
                    result = Admission(
                        allowed=False,
                        code="RATE_LIMITED",
                        status=429,
                        retry_after=retry,
                        client_digest=digest,
                    )
                else:
                    result = Admission(
                        allowed=True, code=None, status=None, retry_after=None, client_digest=digest
                    )
            if retry:
                self._remember_strike(request_id)
            return result
        except Exception:
            return Admission(
                allowed=False,
                code="PROTECTION_UNAVAILABLE",
                status=503,
                retry_after=None,
                client_digest=digest,
            )

    async def record_payload_rejection(
        self, snapshot: AppliedConfig, canonical_ip: str, code: str, request_id: str, now_ms: int
    ) -> None:
        if code not in _SIGNAL_CODES:
            return
        service = snapshot.compiled.document.service
        digest = self.digest(canonical_ip)
        async with self._request_guard:
            if request_id in self._struck:
                return
            try:
                async with self.db.write() as conn:
                    now = await effective_now(conn, now_ms)
                    if not _active(await self._ban_row(conn, service.id, digest), now):
                        await cleanup_expired(conn, "abuse_counters", now)
                        await self._strike(conn, service, digest, request_id, now)
            except Exception as exc:
                raise StorageUnavailable("Protection store unavailable") from exc
            self._remember_strike(request_id)

    def _manual_digest(self, identity: Mapping[str, str]) -> str:
        ip = identity.get("ip")
        digest = identity.get("client_digest")
        if (ip is None) == (digest is None) or set(identity) - {"ip", "client_digest"}:
            raise BanError("INVALID_BAN_IDENTITY", 400)
        if ip is not None:
            try:
                return self.digest(ip)
            except ValueError as exc:
                raise BanError("INVALID_BAN_IDENTITY", 400) from exc
        if not isinstance(digest, str) or not _DIGEST_RE.fullmatch(digest):
            raise BanError("INVALID_BAN_IDENTITY", 400)
        return digest.lower()

    async def create_manual_ban(
        self,
        identity: Mapping[str, str],
        duration: int,
        reason: str,
        admin_id: str,
        now_ms: int,
        *,
        service_id: str | None = None,
    ) -> BanView:
        if (
            type(duration) is not int
            or not 30 <= duration <= 3600
            or reason not in ("operator_action", "demo_test")
        ):
            raise BanError("INVALID_BAN_REQUEST", 400)
        sid = service_id or self.service_id
        if sid is None:
            raise ValueError("Service ID is required for manual bans")
        digest = self._manual_digest(identity)
        async with self.db.write() as conn:
            now = await effective_now(conn, now_ms)
            return await self._create_ban(
                conn, sid, digest, duration, "manual", reason, now, actor_type="admin", actor_id=admin_id
            )

    async def revoke_ban(self, ban_id: str, admin_id: str, now_ms: int) -> RevokeResult:
        try:
            uuid.UUID(ban_id)
        except ValueError as exc:
            raise BanError("BAN_NOT_FOUND", 404) from exc
        async with self.db.write() as conn:
            now = await effective_now(conn, now_ms)
            row = await (await conn.execute("SELECT * FROM bans WHERE ban_id=?", (ban_id,))).fetchone()
            if row is None:
                history = await (
                    await conn.execute(
                        "SELECT service_id,client_digest FROM security_events WHERE event_type='ban.created' AND entity_id=? ORDER BY id DESC LIMIT 1",
                        (ban_id,),
                    )
                ).fetchone()
                if history is None:
                    raise BanError("BAN_NOT_FOUND", 404)
                replacement = await self._ban_row(conn, history["service_id"], history["client_digest"])
                if replacement is None or replacement["ban_id"] == ban_id:
                    raise BanError("BAN_NOT_FOUND", 404)
                raise BanError("BAN_REPLACED", 409)
            if row["revoked_at_ms"] is not None:
                return RevokeResult(ban_id=ban_id, revoked=False)
            await conn.execute("UPDATE bans SET revoked_at_ms=? WHERE ban_id=?", (now, ban_id))
            await conn.execute(
                "DELETE FROM abuse_counters WHERE service_id=? AND client_digest=?",
                (row["service_id"], row["client_digest"]),
            )
            await insert_security_event(
                conn,
                at_ms=now,
                actor_type="admin",
                actor_id=admin_id,
                event_type="ban.revoked",
                service_id=row["service_id"],
                client_digest=row["client_digest"],
                entity_id=ban_id,
            )
            return RevokeResult(ban_id=ban_id, revoked=True)

    async def list_bans(
        self, now_ms: int, *, service_id: str | None = None, state: str = "all", limit: int = 50
    ) -> list[BanView]:
        if state not in ("all", "active", "expired", "revoked") or not 1 <= limit <= 100:
            raise ValueError("Invalid ban listing parameters")
        sid = service_id or self.service_id
        if sid is None:
            raise ValueError("Service ID is required for ban listing")
        async with self.db.read() as conn:
            now = await read_effective_now(conn, now_ms)
            rows = await (
                await conn.execute(
                    "SELECT * FROM bans WHERE service_id=? ORDER BY created_at_ms DESC,ban_id DESC LIMIT ?",
                    (sid, 10_000),
                )
            ).fetchall()
        views = [_ban_view(row, now) for row in rows]
        return [view for view in views if state == "all" or view.status == state][:limit]
