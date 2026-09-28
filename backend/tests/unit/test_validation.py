from __future__ import annotations

import asyncio

import pytest

from shield_api.contracts import Route
from shield_api.validation import BoundedInspector, SchemaRestrictionError, validate_payload, validate_schema


SCHEMA = {
    "type": "object",
    "properties": {"quantity": {"type": "integer", "minimum": 1, "maximum": 5}},
    "required": ["quantity"],
    "additionalProperties": False,
}


def route(schema=SCHEMA, content_types=("application/json",), max_body_bytes=1_048_576):
    return Route(
        id="cart",
        name="Cart",
        path="/cart",
        methods=("POST",),
        max_body_bytes=max_body_bytes,
        content_types=content_types,
        json_schema=schema,
    )


def test_media_and_empty_body_rules():
    plain = route(None, ("text/plain",))
    assert validate_payload(b"", plain) is None
    assert validate_payload(b"x", plain, "text/plain; charset=UTF-8") is None
    assert validate_payload(b"x", plain, "application/json").code == "UNSUPPORTED_MEDIA_TYPE"
    assert validate_payload(b"", route(), "application/json").code == "INVALID_JSON"
    assert validate_payload(b"{}", route(), "application/json", "gzip").status == 415
    assert validate_payload(b"abcdef", plain, "text/plain", max_body_bytes=5).code == "BODY_TOO_LARGE"


def test_json_strictness_and_schema_errors():
    r = route()
    assert validate_payload(b'{"quantity":2}', r, "application/json; charset=utf-8") is None
    for body in (
        b'{"quantity":1,"quantity":2}',
        b'{"quantity":NaN}',
        b'{"quantity":1e999}',
        b"\xff",
        b'{"quantity":',
    ):
        assert validate_payload(body, r, "application/json").code == "INVALID_JSON"
    error = validate_payload(b'{"quantity":6,"password":"secret"}', r, "application/json")
    assert error.code == "SCHEMA_REJECTED"
    assert "secret" not in str(error)
    assert len(error.field_paths) <= 5


def test_json_resource_limits():
    r = route()
    assert (
        validate_payload(b'{"quantity":' + b"9" * 129 + b"}", r, "application/json").code
        == "INSPECTION_LIMIT_EXCEEDED"
    )
    nested = ("[" * 33 + "0" + "]" * 33).encode()
    assert validate_payload(nested, r, "application/json").code == "INSPECTION_LIMIT_EXCEEDED"
    large_nodes = b"[" + b"0," * 20_000 + b"0]"
    assert validate_payload(large_nodes, r, "application/json").code == "INSPECTION_LIMIT_EXCEEDED"


def test_restricted_schema():
    validate_schema(SCHEMA)
    for bad in (
        {"$ref": "file:///etc/passwd"},
        {"type": ["string", "null"]},
        {"pattern": ".*"},
        {"enum": ["x"] * 51},
        {"items": {"items": {"items": {"$ref": "x"}}}},
    ):
        with pytest.raises(SchemaRestrictionError):
            validate_schema(bad)
    too_deep = {"type": "array"}
    for _ in range(13):
        too_deep = {"items": too_deep}
    with pytest.raises(SchemaRestrictionError):
        validate_schema(too_deep)


@pytest.mark.asyncio
async def test_inspector_capacity_held_until_worker_finishes(monkeypatch):
    from shield_api import validation

    original = validation.validate_payload

    def slow(*args, **kwargs):
        import time

        time.sleep(0.1)
        return original(*args, **kwargs)

    monkeypatch.setattr(validation, "validate_payload", slow)
    inspector = BoundedInspector()
    try:
        first = asyncio.create_task(inspector.inspect(b"{}", route(), "application/json"))
        second = asyncio.create_task(inspector.inspect(b"{}", route(), "application/json"))
        await asyncio.sleep(0.01)
        third = await inspector.inspect(b"{}", route(), "application/json")
        assert third.code == "INSPECTION_LIMIT_EXCEEDED"
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        fourth = await inspector.inspect(b"{}", route(), "application/json")
        assert fourth.code == "INSPECTION_LIMIT_EXCEEDED"
        await second
    finally:
        inspector.close()
