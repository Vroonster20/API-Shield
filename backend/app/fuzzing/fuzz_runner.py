"""Exercise safe validation and routing cases against the gateway."""

import httpx

LOGIN_PATH = "/gateway/login"

FUZZ_CASES = (
    {
        "name": "health_check_control",
        "method": "GET",
        "path": "/health",
        "expected_status": 200,
    },
    {
        "name": "login_empty_body",
        "method": "POST",
        "path": LOGIN_PATH,
        "expected_status": 422,
    },
    {
        "name": "login_missing_password",
        "method": "POST",
        "path": LOGIN_PATH,
        "json": {"username": "fuzz-user"},
        "expected_status": 422,
    },
    {
        "name": "login_missing_username",
        "method": "POST",
        "path": LOGIN_PATH,
        "json": {"password": "fuzz-password"},
        "expected_status": 422,
    },
    {
        "name": "login_wrong_types",
        "method": "POST",
        "path": LOGIN_PATH,
        "json": {"username": ["not", "a", "string"], "password": {"x": 1}},
        "expected_status": 422,
    },
    {
        "name": "unsupported_login_method",
        "method": "GET",
        "path": LOGIN_PATH,
        "expected_status": 405,
    },
    {
        "name": "unknown_route",
        "method": "GET",
        "path": "/__api_shield_unknown__",
        "expected_status": 404,
    },
)


async def run_fuzz_suite(
    gateway_base_url: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[dict[str, str | int | bool]]:
    results: list[dict[str, str | int | bool]] = []
    async with httpx.AsyncClient(
        base_url=gateway_base_url.rstrip("/"),
        timeout=5.0,
        follow_redirects=False,
        transport=transport,
    ) as client:
        for case in FUZZ_CASES:
            try:
                response = await client.request(
                    case["method"], case["path"], json=case.get("json")
                )
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