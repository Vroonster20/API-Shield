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

# Login currently uses GET in the gateway. Update these if B07 changes it.
FUZZ_CASES = [
    {"name": "health_control", "method": "GET", "path": "/health",
     "expected": 200, "body": {}},
    {"name": "missing_login_fields", "method": "GET", "path": "/login",
     "expected": 422, "body": {"json": {}}},
    {"name": "missing_password", "method": "GET", "path": "/login",
     "expected": 422, "body": {"json": {"username": "test"}}},
    {"name": "numeric_username", "method": "GET", "path": "/login",
     "expected": 422, "body": {"json": {"username": 123, "password": "test"}}},
    {"name": "null_password", "method": "GET", "path": "/login",
     "expected": 422, "body": {"json": {"username": "test", "password": None}}},
    {"name": "invalid_json", "method": "GET", "path": "/login",
     "expected": 422, "body": {"content": "{", "headers": {"Content-Type": "application/json"}}},
    {"name": "missing_order_fields", "method": "POST", "path": "/db/orders",
     "expected": 422, "body": {"json": {}}},
    {"name": "order_is_a_list", "method": "POST", "path": "/db/orders",
     "expected": 422, "body": {"json": []}},
    {"name": "missing_payment_fields", "method": "POST", "path": "/webhooks/payments",
     "expected": 422, "body": {"json": {}}},
    {"name": "valid_format_wrong_credentials", "method": "GET", "path": "/login",
     "expected": 401, "body": {"json": {
         "username": "b09_nonexistent_user", "password": "b09_wrong_password",
     }}},
]


def run_fuzz_suite(gateway_base_url: str) -> list[dict]:
    """Returns a list of {name, expected, actual, passed} dicts."""
    results = []
    with httpx.Client(base_url=gateway_base_url, timeout=5.0, trust_env=False) as client:
        for case in FUZZ_CASES:
            result = {
                "name": case["name"],
                "expected": case["expected"],
                "actual": None,
                "passed": False,
            }
            try:
                response = client.request(case["method"], case["path"], **case["body"])
                result["actual"] = response.status_code
                result["passed"] = response.status_code == case["expected"]
            except httpx.RequestError as error:
                result["error"] = str(error)
            results.append(result)
    return results
