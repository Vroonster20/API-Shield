"""Development-only generated payload checks; the UI runner uses fixed cases."""

from __future__ import annotations

import json
import string

from hypothesis import given, settings, strategies as st

from shield_api.contracts import Route
from shield_api.validation import validate_payload


SCHEMA = {
    "type": "object",
    "required": ["username", "quantity"],
    "additionalProperties": False,
    "properties": {
        "username": {"type": "string", "minLength": 1, "maxLength": 20},
        "quantity": {"type": "integer", "minimum": 1, "maximum": 10},
    },
}
ROUTE = Route(
    id="synthetic",
    name="Synthetic",
    path="/synthetic",
    methods=("POST",),
    max_body_bytes=1024,
    content_types=("application/json",),
    json_schema=SCHEMA,
)


@settings(max_examples=100)
@given(
    name=st.text(alphabet=string.ascii_letters + string.digits, min_size=1, max_size=20),
    quantity=st.integers(min_value=1, max_value=10),
    separators=st.sampled_from(((",", ":"), (", ", ": "))),
)
def test_valid_serialized_bytes_are_accepted_unchanged(name, quantity, separators):
    raw = json.dumps({"username": name, "quantity": quantity}, separators=separators).encode()
    before = raw[:]
    assert validate_payload(raw, ROUTE, "application/json; charset=UTF-8") is None
    assert raw == before


@settings(max_examples=100)
@given(
    name_suffix=st.text(alphabet=string.ascii_letters, min_size=1, max_size=10),
    quantity=st.one_of(st.integers(max_value=0, min_value=-1000), st.integers(min_value=11, max_value=1000)),
)
def test_out_of_range_payload_is_rejected_without_value_leak(name_suffix, quantity):
    name = "SECRET_" + name_suffix
    raw = json.dumps({"username": name, "quantity": quantity}).encode()
    violation = validate_payload(raw, ROUTE, "application/json")
    assert violation.code == "SCHEMA_REJECTED"
    assert violation.status == 400
    assert len(violation.field_paths) <= 5
    assert name not in str(violation)


@settings(max_examples=100)
@given(
    first=st.integers(min_value=1, max_value=10),
    second=st.integers(min_value=1, max_value=10),
    tail=st.binary(max_size=32),
)
def test_duplicate_keys_and_invalid_utf8_never_pass(first, second, tail):
    duplicate = f'{{"username":"user","quantity":{first},"quantity":{second}}}'.encode()
    assert validate_payload(duplicate, ROUTE, "application/json").code == "INVALID_JSON"
    invalid_utf8 = b'{"username":"user","quantity":1}' + b"\xff" + tail
    assert validate_payload(invalid_utf8, ROUTE, "application/json").code == "INVALID_JSON"
