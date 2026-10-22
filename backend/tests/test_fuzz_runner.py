import asyncio

import httpx

from app.fuzzing.fuzz_runner import FUZZ_CASES, run_fuzz_suite
from main import app


def test_fuzz_suite_reports_real_gateway_statuses():
    results = asyncio.run(
        run_fuzz_suite(
            "http://gateway.test/",
            transport=httpx.ASGITransport(app=app),
        )
    )

    assert len(results) == len(FUZZ_CASES)
    assert all(result["passed"] for result in results)
    assert [result["actual"] for result in results] == [
        case["expected_status"] for case in FUZZ_CASES
    ]


def test_fuzz_suite_reports_gateway_connection_errors():
    def fail_request(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("gateway unavailable", request=request)

    results = asyncio.run(
        run_fuzz_suite(
            "http://gateway.test",
            transport=httpx.MockTransport(fail_request),
        )
    )

    assert len(results) == len(FUZZ_CASES)
    assert all(result["passed"] is False for result in results)
    assert all(
        str(result["actual"]).startswith("request error:")
        for result in results
    )
