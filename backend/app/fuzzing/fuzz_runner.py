"""Exercise safe validation and routing cases against the gateway."""

import httpx


FUZZ_CASES = (
    {
        "name": "health_check_control",
        "method": "GET",
        "path": "/health",
        "expected_status": 200,
    },
    {
        "name": "missing_login_fields",
        "method": "POST",
        "path": "/login",
        "expected_status": 422,
    },
    {
        "name": "missing_login_password",
        "method": "POST",
        "path": "/login?username=fuzz-user",
        "expected_status": 422,
    },
    {
        "name": "missing_login_username",
        "method": "POST",
        "path": "/login?password=fuzz-password",
        "expected_status": 422,
    },
    {
        "name": "unsupported_login_method",
        "method": "GET",
        "path": "/login",
        "expected_status": 405,
    },
    {
        "name": "unknown_route",
        "method": "GET",
        "path": "/__api_shield_unknown__",
        "expected_status": 404,
    },
)


async def run_fuzz_suite(gateway_base_url: str) -> list[dict[str, str | int | bool]]:
    """Return actual outcomes for a fixed set of safe gateway requests."""
    results: list[dict[str, str | int | bool]] = []
    async with httpx.AsyncClient(
        base_url=gateway_base_url.rstrip("/"),
        timeout=5.0,
        follow_redirects=False,
    ) as client:
        for case in FUZZ_CASES:
            try:
                response = await client.request(case["method"], case["path"])
                actual: str | int = response.status_code
            except httpx.RequestError as error:
                actual = f"request error: {error}"

            results.append(
                {
                    "name": case["name"],
                    "expected": case["expected_status"],
                    "actual": actual,
                    "passed": actual == case["expected_status"],
                }
            )
    return results
