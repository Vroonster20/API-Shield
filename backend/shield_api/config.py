"""Configuration validation, compilation, and versioned application."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import os
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .contracts import (
    AppliedConfig,
    CompiledConfig,
    CompiledRoute,
    Config,
    ConfigInvalid,
    PendingApply,
    Registry,
)
from .db import Database, StorageUnavailable, insert_security_event
from .validation import SchemaRestrictionError, validate_schema


HOST_RE = re.compile(
    r"(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*\Z"
)
LITERAL_RE = re.compile(r"[A-Za-z0-9._~-]+\Z")
PARAM_RE = re.compile(r"\{[a-z][a-z0-9_]{0,63}\}\Z")
MEDIA_RE = re.compile(r"[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+\Z")
SCHEMA_KEYS = frozenset(
    {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "minItems",
        "maxItems",
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
        "enum",
        "const",
        "title",
        "description",
        "$schema",
    }
)
TYPES = frozenset({"null", "boolean", "object", "array", "number", "integer", "string"})
SCHEMA_URI = "https://json-schema.org/draft/2020-12/schema"


class _FrozenDict(dict):
    def _blocked(self, *_: object, **__: object) -> None:
        raise TypeError("Compiled configuration is immutable")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _blocked


class _FrozenList(list):
    def _blocked(self, *_: object, **__: object) -> None:
        raise TypeError("Compiled configuration is immutable")

    __setitem__ = __delitem__ = append = clear = extend = insert = pop = remove = reverse = sort = (
        __iadd__
    ) = __imul__ = _blocked


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return _FrozenDict({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return _FrozenList([_freeze(item) for item in value])
    return value


def _compact(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _safe_pydantic_errors(exc: ValidationError) -> list[str]:
    return [f"{'.'.join(str(part) for part in error['loc'])}: {error['type']}" for error in exc.errors()[:20]]


def _path_segments(path: str) -> tuple[str, ...]:
    if not path.startswith("/") or len(path.encode("utf-8")) > 8192 or "//" in path:
        raise ConfigInvalid(["route.path: invalid absolute path"])
    if path == "/":
        return ()
    segments = tuple(path[1:].split("/"))
    if any(
        (not (LITERAL_RE.fullmatch(s) or PARAM_RE.fullmatch(s)) or s in (".", "..")) for s in segments[:-1]
    ) or (
        segments[-1] != ""
        and (
            not (LITERAL_RE.fullmatch(segments[-1]) or PARAM_RE.fullmatch(segments[-1]))
            or segments[-1] in (".", "..")
        )
    ):
        raise ConfigInvalid(["route.path: only literal and whole parameter segments are allowed"])
    return segments


def _patterns_intersect(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    if len(left) != len(right):
        return False
    return all(a == b or PARAM_RE.fullmatch(a) or PARAM_RE.fullmatch(b) for a, b in zip(left, right))


def _bounded_scalar(value: Any) -> bool:
    return (
        value is None
        or isinstance(value, bool)
        or (
            type(value) in (int, float)
            and (type(value) is int or math.isfinite(value))
            and len(str(value)) <= 128
        )
        or (isinstance(value, str) and len(value) <= 256)
    )


def _check_schema(schema: Any) -> None:
    if not isinstance(schema, dict):
        raise ConfigInvalid(["json_schema: expected object"])
    if len(_compact(schema).encode("utf-8")) > 16_384:
        raise ConfigInvalid(["json_schema: exceeds 16 KiB"])
    nodes = 0

    def walk(node: dict[str, Any], depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > 200 or depth > 12:
            raise ConfigInvalid(["json_schema: depth or node limit exceeded"])
        if unknown := set(node) - SCHEMA_KEYS:
            raise ConfigInvalid([f"json_schema: unsupported keyword {sorted(unknown)[0]}"])
        if "$schema" in node and (depth != 1 or node["$schema"] != SCHEMA_URI):
            raise ConfigInvalid(["json_schema: unsupported $schema"])
        if "type" in node and (type(node["type"]) is not str or node["type"] not in TYPES):
            raise ConfigInvalid(["json_schema.type: one standard type required"])
        for key in ("title", "description"):
            if key in node and (type(node[key]) is not str or len(node[key]) > 256):
                raise ConfigInvalid([f"json_schema.{key}: bounded string required"])
        for key in ("minItems", "maxItems", "minLength", "maxLength"):
            if key in node and (type(node[key]) is not int or not 0 <= node[key] <= 20_000):
                raise ConfigInvalid([f"json_schema.{key}: invalid bound"])
        for key in ("minimum", "maximum"):
            if key in node and (type(node[key]) not in (int, float) or not _bounded_scalar(node[key])):
                raise ConfigInvalid([f"json_schema.{key}: finite number required"])
        for low, high in (("minItems", "maxItems"), ("minLength", "maxLength"), ("minimum", "maximum")):
            if low in node and high in node and node[low] > node[high]:
                raise ConfigInvalid([f"json_schema: {low} exceeds {high}"])
        if "additionalProperties" in node and type(node["additionalProperties"]) is not bool:
            raise ConfigInvalid(["json_schema.additionalProperties: boolean required"])
        if "required" in node and (
            not isinstance(node["required"], list)
            or any(type(x) is not str for x in node["required"])
            or len(set(node["required"])) != len(node["required"])
        ):
            raise ConfigInvalid(["json_schema.required: unique string array required"])
        for key in ("enum", "const"):
            if key in node:
                values = node[key] if key == "enum" else [node[key]]
                if key == "enum" and (not isinstance(values, list) or not 1 <= len(values) <= 50):
                    raise ConfigInvalid(["json_schema.enum: 1..50 values required"])
                if any(not _bounded_scalar(item) for item in values):
                    raise ConfigInvalid([f"json_schema.{key}: bounded scalar required"])
        properties = node.get("properties", {})
        if not isinstance(properties, dict) or any(
            type(k) is not str or not k or len(k) > 256 for k in properties
        ):
            raise ConfigInvalid(["json_schema.properties: invalid object"])
        for child in properties.values():
            if not isinstance(child, dict):
                raise ConfigInvalid(["json_schema.properties: schema object required"])
            walk(child, depth + 1)
        if "items" in node:
            if not isinstance(node["items"], dict):
                raise ConfigInvalid(["json_schema.items: one schema object required"])
            walk(node["items"], depth + 1)

    walk(schema, 1)


def compile_config(document: Config | Mapping[str, Any], registry: Registry) -> CompiledConfig:
    """Compile a complete frozen policy or raise safe ConfigInvalid errors."""
    try:
        if not isinstance(document, Config):
            if len(_compact(document).encode("utf-8")) > 262_144:
                raise ConfigInvalid(["config: exceeds 256 KiB"])
            document = Config.model_validate(document)
        else:
            serialized = document.model_dump(mode="json")
            if len(_compact(serialized).encode("utf-8")) > 262_144:
                raise ConfigInvalid(["config: exceeds 256 KiB"])
            document = Config.model_validate(serialized)
    except ValidationError as exc:
        raise ConfigInvalid(_safe_pydantic_errors(exc)) from None
    except (TypeError, ValueError) as exc:
        if isinstance(exc, ConfigInvalid):
            raise
        raise ConfigInvalid(["config: invalid JSON value"]) from None
    service = document.service
    if not HOST_RE.fullmatch(service.public_host):
        raise ConfigInvalid(["service.public_host: lowercase DNS hostname required"])
    ids = [upstream.id for upstream in registry.upstreams]
    if len(ids) != len(set(ids)):
        raise ConfigInvalid(["registry: duplicate upstream IDs"])
    upstream = next((item for item in registry.upstreams if item.id == service.upstream_id), None)
    if upstream is None:
        raise ConfigInvalid(["service.upstream_id: unknown approved upstream"])
    try:
        ipaddress.ip_address(upstream.host)
        host_valid = True
    except ValueError:
        host_valid = bool(HOST_RE.fullmatch(upstream.host))
    if not host_valid:
        raise ConfigInvalid(["registry: upstream host is invalid"])
    route_ids: set[str] = set()
    compiled: list[CompiledRoute] = []
    for route in service.routes:
        if route.id in route_ids:
            raise ConfigInvalid(["service.routes: duplicate route IDs"])
        route_ids.add(route.id)
        if route.max_body_bytes > service.max_body_bytes:
            raise ConfigInvalid([f"route {route.id}: body cap exceeds service cap"])
        if len(set(route.methods)) != len(route.methods):
            raise ConfigInvalid([f"route {route.id}: duplicate methods"])
        if len(set(route.content_types)) != len(route.content_types) or any(
            not MEDIA_RE.fullmatch(media) for media in route.content_types
        ):
            raise ConfigInvalid([f"route {route.id}: invalid content types"])
        if route.json_schema is not None:
            _check_schema(route.json_schema)
            try:
                validate_schema(route.json_schema)
            except SchemaRestrictionError as exc:
                raise ConfigInvalid([f"route {route.id}: restricted JSON schema invalid"]) from exc
            if not any(
                media == "application/json" or media.endswith("+json") for media in route.content_types
            ):
                raise ConfigInvalid([f"route {route.id}: JSON schema requires explicit JSON content type"])
            object.__setattr__(route, "json_schema", _freeze(route.json_schema))
        segments = _path_segments(route.path)
        compiled.append(
            CompiledRoute(route, segments, sum(not PARAM_RE.fullmatch(part) for part in segments))
        )
    for index, left in enumerate(compiled):
        for right in compiled[index + 1 :]:
            if (
                left.literal_count == right.literal_count
                and set(left.route.methods) & set(right.route.methods)
                and _patterns_intersect(left.segments, right.segments)
            ):
                raise ConfigInvalid([f"service.routes: ambiguous overlap {left.route.id}/{right.route.id}"])
    return CompiledConfig(document, upstream, tuple(compiled))


class ConfigConflict(RuntimeError):
    pass


class GatewayAlreadyRunning(RuntimeError):
    pass


class GatewayRuntimeLock:
    """A same-host process lock for the one allowed gateway worker."""

    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "gateway.lock"
        self._file = None

    def acquire(self) -> None:
        if self._file is not None:
            raise GatewayAlreadyRunning("Gateway lock already held")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            handle.seek(0)
            handle.write(b"\0")
            handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise GatewayAlreadyRunning("Another gateway owns the runtime") from exc
        self._file = handle

    def release(self) -> None:
        if self._file is None:
            return
        handle, self._file = self._file, None
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()

    def __enter__(self) -> "GatewayRuntimeLock":
        self.acquire()
        return self

    def __exit__(self, *_: object) -> None:
        self.release()


@dataclass(frozen=True, slots=True)
class ConfigStatus:
    desired_version: int | None
    applied_version: int | None
    heartbeat_ms: int | None
    apply_error_code: str | None
    apply_error_version: int | None
    status: str
    gateway_instance_id: str | None
    started_at_ms: int | None
    dropped_events_since_start: int | None


class ConfigStore:
    def __init__(self, db: Database, registry: Registry, *, clock: Callable[[], int] | None = None) -> None:
        self.db = db
        self.registry = registry
        self.clock = clock or (lambda: int(time.time() * 1000))
        self._snapshot: AppliedConfig | None = None

    @property
    def snapshot(self) -> AppliedConfig | None:
        return self._snapshot

    async def load_snapshot(self) -> AppliedConfig | None:
        async with self.db.read() as conn:
            row = await (
                await conn.execute(
                    "SELECT r.applied_version,c.document_json FROM runtime_config r LEFT JOIN config_revisions c ON c.version=r.applied_version WHERE r.singleton=1"
                )
            ).fetchone()
        if row and row["applied_version"] is not None:
            try:
                candidate = AppliedConfig(
                    row["applied_version"], compile_config(json.loads(row["document_json"]), self.registry)
                )
            except (ConfigInvalid, TypeError, ValueError) as exc:
                raise StorageUnavailable("Applied configuration unavailable") from exc
            self._snapshot = candidate
        return self._snapshot

    async def load_desired(self) -> tuple[int | None, Config | None]:
        async with self.db.read() as conn:
            row = await (
                await conn.execute(
                    "SELECT r.desired_version,c.document_json FROM runtime_config r LEFT JOIN config_revisions c ON c.version=r.desired_version WHERE r.singleton=1"
                )
            ).fetchone()
        if not row or row["desired_version"] is None:
            return None, None
        return row["desired_version"], Config.model_validate_json(row["document_json"])

    async def apply_config(
        self, expected_version: int | None, document: Config | Mapping[str, Any], admin_id: str
    ) -> PendingApply:
        compiled = compile_config(document, self.registry)
        encoded = _compact(compiled.document.model_dump(mode="json"))
        checksum = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        async with self.db.write() as conn:
            row = await (
                await conn.execute(
                    "SELECT desired_version,applied_version FROM runtime_config WHERE singleton=1"
                )
            ).fetchone()
            if row["desired_version"] != expected_version:
                raise ConfigConflict("Configuration version changed")
            if row["desired_version"] is not None:
                old = await (
                    await conn.execute(
                        "SELECT document_json FROM config_revisions WHERE version=?",
                        (row["desired_version"],),
                    )
                ).fetchone()
                old_id = json.loads(old["document_json"])["service"]["id"]
                if old_id != compiled.document.service.id:
                    raise ConfigInvalid(["service.id: immutable after initial save"])
            version = (
                await (
                    await conn.execute("SELECT COALESCE(MAX(version),0)+1 AS next FROM config_revisions")
                ).fetchone()
            )["next"]
            at_ms = self.clock()
            await conn.execute(
                "INSERT INTO config_revisions(version,document_json,checksum,actor_admin_id,created_at_ms) VALUES(?,?,?,?,?)",
                (version, encoded, checksum, admin_id, at_ms),
            )
            await conn.execute(
                "UPDATE runtime_config SET desired_version=?,apply_error_code=NULL,apply_error_version=NULL WHERE singleton=1",
                (version,),
            )
            await insert_security_event(
                conn,
                at_ms=at_ms,
                actor_type="admin",
                actor_id=admin_id,
                event_type="config.applied_requested",
                service_id=compiled.document.service.id,
                entity_id=str(version),
                safe_details={"version": version},
            )
            return PendingApply(desired_version=version, applied_version=row["applied_version"])

    async def poll_and_apply(self) -> AppliedConfig | None:
        async with self.db.read() as conn:
            row = await (
                await conn.execute(
                    "SELECT r.desired_version,c.document_json FROM runtime_config r LEFT JOIN config_revisions c ON c.version=r.desired_version WHERE r.singleton=1"
                )
            ).fetchone()
        desired_version = row["desired_version"] if row else None
        if desired_version is None:
            return self._snapshot
        if self._snapshot and self._snapshot.version == desired_version:
            return self._snapshot
        try:
            document = json.loads(row["document_json"])
            compiled = compile_config(document, self.registry)
        except (ConfigInvalid, TypeError, ValueError):
            async with self.db.write() as conn:
                old = await (
                    await conn.execute(
                        "SELECT apply_error_version FROM runtime_config WHERE singleton=1 AND desired_version=?",
                        (desired_version,),
                    )
                ).fetchone()
                if old and old["apply_error_version"] != desired_version:
                    await conn.execute(
                        "UPDATE runtime_config SET apply_error_code='CONFIG_INVALID',apply_error_version=? WHERE singleton=1",
                        (desired_version,),
                    )
                    await insert_security_event(
                        conn,
                        at_ms=self.clock(),
                        actor_type="system",
                        event_type="config.apply_failed",
                        entity_id=str(desired_version),
                        safe_details={"code": "CONFIG_INVALID"},
                    )
            return self._snapshot
        candidate = AppliedConfig(desired_version, compiled)
        # A newer save may occur during compilation; acknowledge only the version actually loaded.
        async with self.db.write() as conn:
            row = await (
                await conn.execute("SELECT desired_version FROM runtime_config WHERE singleton=1")
            ).fetchone()
            if row["desired_version"] != desired_version:
                return self._snapshot
            await conn.execute(
                "UPDATE runtime_config SET applied_version=?,applied_at_ms=?,apply_error_code=NULL,apply_error_version=NULL WHERE singleton=1",
                (desired_version, self.clock()),
            )
        self._snapshot = candidate
        return candidate

    async def heartbeat(
        self, gateway_instance_id: str, started_at_ms: int, dropped_events_since_start: int
    ) -> None:
        async with self.db.write() as conn:
            await conn.execute(
                "UPDATE runtime_config SET heartbeat_ms=?,gateway_instance_id=?,started_at_ms=?,dropped_events_since_start=? WHERE singleton=1",
                (self.clock(), gateway_instance_id, started_at_ms, dropped_events_since_start),
            )

    async def status(self) -> ConfigStatus:
        async with self.db.read() as conn:
            row = await (await conn.execute("SELECT * FROM runtime_config WHERE singleton=1")).fetchone()
        now = self.clock()
        if row["desired_version"] is None:
            status = "unconfigured"
        elif row["heartbeat_ms"] is None or now - row["heartbeat_ms"] > 15_000:
            status = "stale"
        elif row["apply_error_version"] == row["desired_version"]:
            status = "failed"
        elif row["applied_version"] == row["desired_version"]:
            status = "applied"
        else:
            status = "pending"
        return ConfigStatus(
            *(
                row[key]
                for key in (
                    "desired_version",
                    "applied_version",
                    "heartbeat_ms",
                    "apply_error_code",
                    "apply_error_version",
                )
            ),
            status,
            *(row[key] for key in ("gateway_instance_id", "started_at_ms", "dropped_events_since_start")),
        )
