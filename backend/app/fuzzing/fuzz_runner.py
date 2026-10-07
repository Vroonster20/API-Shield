"""
[Task B09] Fuzz test runner.

Fires a fixed set of ~10 hardcoded bad requests at the GATEWAY's own
routes (not the target directly -- you're testing that the gateway's
validation catches them) and returns pass/fail per case.

A "pass" means the gateway correctly rejected a bad request (or
correctly accepted a good one, for a control case) -- not that nothing
crashed.
"""
import httpx

# TODO [B09]: define fixed test cases, e.g.:
# FUZZ_CASES = [
#     {"name": "missing_field", "payload": {}, "expect_status": 422},
#     {"name": "wrong_type", "payload": {"product_id": "not_a_number"}, "expect_status": 422},
#     {"name": "oversized_payload", "payload": {"note": "x" * 100000}, "expect_status": 422},
#     {"name": "valid_control", "payload": {"product_id": 1, "quantity": 2}, "expect_status": 200},
#     # ... more cases
# ]


def run_fuzz_suite(gateway_base_url: str) -> list[dict]:
    """Returns a list of {name, expected, actual, passed} dicts."""
    raise NotImplementedError
