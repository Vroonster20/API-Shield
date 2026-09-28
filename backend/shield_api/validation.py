"""Bounded, side-effect-free request payload inspection.

The gateway owns streaming the body and enforcing its receive deadline.  This
module inspects the resulting original bytes; it never reserializes them.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore
from typing import Any

from jsonschema import Draft202012Validator

from .contracts import Route, Violation

MAX_BODY_BYTES = 1_048_576
MAX_SCHEMA_BYTES = 16_384
MAX_SCHEMA_DEPTH = 12
MAX_SCHEMA_NODES = 200
MAX_INSTANCE_DEPTH = 32
MAX_INSTANCE_NODES = 20_000
MAX_NUMBER_TOKEN = 128
_SCHEMA_URI = "https://json-schema.org/draft/2020-12/schema"
_SCHEMA_KEYS = frozenset(
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
    }
)
_TYPES = frozenset({"null", "boolean", "object", "array", "number", "integer", "string"})
_MEDIA_RE = re.compile(r"^[!#$%&'*+.^_`|~0-9a-z-]+/[!#$%&'*+.^_`|~0-9a-z-]+$")


class SchemaRestrictionError(ValueError):
    """A schema cannot be evaluated within the supported restricted subset."""


class _InspectionLimit(ValueError):
    pass


class _InvalidJSON(ValueError):
    pass


def normalized_media_type(value: str | None) -> str | None:
    if value is None:
        return None
    token = value.split(";", 1)[0].strip().lower()
    return token if _MEDIA_RE.fullmatch(token) else None


def is_json_media_type(value: str | None) -> bool:
    media = normalized_media_type(value)
    return media == "application/json" or bool(
        media and media.startswith("application/") and media.endswith("+json")
    )


def _bounded_scalar(value: Any) -> bool:
    return (
        value is None
        or type(value) in (bool, int, float, str)
        and (type(value) is not str or len(value) <= 256)
        and (type(value) is not float or math.isfinite(value))
    )


def validate_schema(schema: dict[str, object]) -> None:
    """Reject all active JSON Schema features outside the fixed local subset."""
    if not isinstance(schema, dict):
        raise SchemaRestrictionError("Schema root must be an object")
    try:
        encoded = json.dumps(schema, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(
            "utf-8"
        )
    except (TypeError, ValueError, UnicodeError) as exc:
        raise SchemaRestrictionError("Schema is not finite JSON") from exc
    if len(encoded) > MAX_SCHEMA_BYTES:
        raise SchemaRestrictionError("Schema exceeds 16 KiB")
    nodes = 0

    def walk(part: Any, depth: int, root: bool = False) -> None:
        nonlocal nodes
        nodes += 1
        if depth > MAX_SCHEMA_DEPTH or nodes > MAX_SCHEMA_NODES:
            raise SchemaRestrictionError("Schema complexity limit exceeded")
        if not isinstance(part, dict):
            raise SchemaRestrictionError("Each schema must be an object")
        unknown = set(part) - _SCHEMA_KEYS - ({"$schema"} if root else set())
        if unknown:
            raise SchemaRestrictionError("Unsupported schema keyword")
        if "$schema" in part and part["$schema"] != _SCHEMA_URI:
            raise SchemaRestrictionError("Unsupported schema version")
        if "type" in part and (type(part["type"]) is not str or part["type"] not in _TYPES):
            raise SchemaRestrictionError("Schema type must be one standard type")
        for key in ("title", "description"):
            if key in part and type(part[key]) is not str:
                raise SchemaRestrictionError("Schema annotation must be text")
        for key in ("minItems", "maxItems", "minLength", "maxLength"):
            if key in part and (type(part[key]) is not int or part[key] < 0):
                raise SchemaRestrictionError("Schema bound must be a nonnegative integer")
        for lower, upper in (("minItems", "maxItems"), ("minLength", "maxLength"), ("minimum", "maximum")):
            if lower in part and upper in part and part[lower] > part[upper]:
                raise SchemaRestrictionError("Schema bounds are reversed")
        for key in ("minimum", "maximum"):
            if key in part:
                try:
                    finite = type(part[key]) in (int, float) and math.isfinite(part[key])
                except OverflowError:
                    finite = False
                if not finite:
                    raise SchemaRestrictionError("Schema numeric bound must be finite")
        if "additionalProperties" in part and type(part["additionalProperties"]) is not bool:
            raise SchemaRestrictionError("additionalProperties must be boolean")
        if "required" in part:
            required = part["required"]
            if (
                not isinstance(required, list)
                or any(type(item) is not str for item in required)
                or len(set(required)) != len(required)
            ):
                raise SchemaRestrictionError("required must contain unique property names")
        if "properties" in part:
            properties = part["properties"]
            if not isinstance(properties, dict) or any(type(key) is not str for key in properties):
                raise SchemaRestrictionError("properties must be an object")
            for child in properties.values():
                walk(child, depth + 1)
        if "items" in part:
            walk(part["items"], depth + 1)
        if "enum" in part:
            values = part["enum"]
            if (
                not isinstance(values, list)
                or not 1 <= len(values) <= 50
                or any(not _bounded_scalar(value) for value in values)
            ):
                raise SchemaRestrictionError("enum must contain 1–50 bounded scalars")
        if "const" in part and not _bounded_scalar(part["const"]):
            raise SchemaRestrictionError("const must be a bounded scalar")

    walk(schema, 0, True)
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as exc:
        raise SchemaRestrictionError("Invalid restricted schema") from exc


def _parse_json(raw: bytes) -> Any:
    try:
        source = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise _InvalidJSON("Invalid UTF-8") from exc

    def number(token: str) -> int | float:
        if len(token) > MAX_NUMBER_TOKEN:
            raise _InspectionLimit("Numeric token too long")
        result = float(token) if any(char in token for char in ".eE") else int(token)
        if type(result) is float and not math.isfinite(result):
            raise _InvalidJSON("Nonfinite number")
        return result

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise _InvalidJSON("Duplicate property")
            result[key] = value
        return result

    try:
        value = json.loads(
            source,
            parse_int=number,
            parse_float=number,
            parse_constant=lambda _: (_ for _ in ()).throw(_InvalidJSON("Nonfinite number")),
            object_pairs_hook=pairs,
        )
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise _InvalidJSON("Malformed JSON") from exc
    except RecursionError as exc:
        raise _InspectionLimit("JSON nesting limit exceeded") from exc
    pending = [(value, 0)]
    count = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if depth > MAX_INSTANCE_DEPTH or count > MAX_INSTANCE_NODES:
            raise _InspectionLimit("JSON complexity limit exceeded")
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
    return value


def _violation(code: str, status: int, message: str, paths: tuple[str, ...] = ()) -> Violation:
    return Violation(code=code, status=status, message=message, field_paths=paths)


def validate_payload(
    raw_bytes: bytes,
    route: Route | None,
    content_type: str | None = None,
    content_encoding: str | None = None,
    *,
    max_body_bytes: int | None = None,
) -> Violation | None:
    """Validate already buffered bytes without changing them or exposing values."""
    if content_encoding and content_encoding.strip().lower() != "identity":
        return _violation("UNSUPPORTED_CONTENT_ENCODING", 415, "Request content encoding is unsupported")
    limit = min(
        MAX_BODY_BYTES,
        route.max_body_bytes if route else MAX_BODY_BYTES,
        max_body_bytes if max_body_bytes is not None else MAX_BODY_BYTES,
    )
    if len(raw_bytes) > limit:
        return _violation("BODY_TOO_LARGE", 413, "Request body exceeds configured limit")
    if route is None:
        return None
    schema = route.json_schema
    if not raw_bytes and schema is None:
        return None
    media = normalized_media_type(content_type)
    allowed = {normalized_media_type(item) for item in route.content_types}
    if route.content_types and media not in allowed:
        return _violation("UNSUPPORTED_MEDIA_TYPE", 415, "Request media type is unsupported")
    if schema is None:
        return None
    # Configuration compilation guarantees this, but fail closed for a direct caller.
    if not route.content_types or not is_json_media_type(media):
        return _violation("UNSUPPORTED_MEDIA_TYPE", 415, "JSON media type is required")
    try:
        value = _parse_json(raw_bytes)
    except _InspectionLimit:
        return _violation("INSPECTION_LIMIT_EXCEEDED", 413, "JSON inspection limit exceeded")
    except _InvalidJSON:
        return _violation("INVALID_JSON", 400, "Request JSON is invalid")
    try:
        validate_schema(schema)
        errors = []
        for error in Draft202012Validator(schema).iter_errors(value):
            path = "/" + "/".join(
                str(segment).replace("~", "~0").replace("/", "~1")[:80] for segment in error.absolute_path
            )
            errors.append(path[:512])
            if len(errors) == 5:
                break
    except SchemaRestrictionError:
        return _violation("INSPECTION_LIMIT_EXCEEDED", 413, "JSON schema cannot be evaluated")
    if errors:
        return _violation("SCHEMA_REJECTED", 400, "Request JSON does not match schema", tuple(errors))
    return None


class BoundedInspector:
    """At most two live parser jobs; cancelled awaits retain their worker slot."""

    def __init__(self) -> None:
        self._slots = BoundedSemaphore(2)
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="shield-json")

    async def inspect(
        self,
        raw_bytes: bytes,
        route: Route | None,
        content_type: str | None = None,
        content_encoding: str | None = None,
        *,
        max_body_bytes: int | None = None,
    ) -> Violation | None:
        if not self._slots.acquire(blocking=False):
            return _violation("INSPECTION_LIMIT_EXCEEDED", 503, "JSON inspection capacity is full")
        loop = asyncio.get_running_loop()

        def run() -> Violation | None:
            try:
                return validate_payload(
                    raw_bytes, route, content_type, content_encoding, max_body_bytes=max_body_bytes
                )
            finally:
                self._slots.release()

        try:
            future = loop.run_in_executor(self._pool, run)
        except BaseException:
            self._slots.release()
            raise
        return await asyncio.shield(future)

    def close(self) -> None:
        self._pool.shutdown(wait=True, cancel_futures=False)
