"""B09 fuzz reporting without making external requests."""
import httpx

from app.fuzzing import fuzz_runner


def use_mock_gateway(monkeypatch, handler):
    client_class = httpx.Client

    def make_client(base_url, timeout, trust_env):
        return client_class(
            base_url=base_url,
            timeout=timeout,
            trust_env=trust_env,
            transport=httpx.MockTransport(handler),
        )

    monkeypatch.setattr(fuzz_runner.httpx, "Client", make_client)


def test_fuzz_sends_cases_and_checks_expected_status(monkeypatch):
    requests = []

    def handler(request):
        case = fuzz_runner.FUZZ_CASES[len(requests)]
        requests.append(request)
        assert request.url.host == "127.0.0.1"
        assert request.url.port == 8000
        assert request.method == case["method"]
        assert request.url.path == case["path"]
        return httpx.Response(case["expected"])

    use_mock_gateway(monkeypatch, handler)
    results = fuzz_runner.run_fuzz_suite("http://127.0.0.1:8000")
    assert len(results) == 10
    assert len(requests) == 10
    for result in results:
        assert result["passed"], result["name"]
    assert requests[5].content == b"{"


def test_unexpected_rejections_are_failures(monkeypatch):
    def handler(request):
        return httpx.Response(status)

    use_mock_gateway(monkeypatch, handler)
    for status in [403, 429, 500]:
        results = fuzz_runner.run_fuzz_suite("http://127.0.0.1:8000")
        for result in results:
            assert not result["passed"], result["name"]
            assert result["actual"] == status


def test_timeout_is_reported_and_next_cases_still_run(monkeypatch):
    requests = []

    def handler(request):
        case = fuzz_runner.FUZZ_CASES[len(requests)]
        requests.append(request)
        if len(requests) == 1:
            raise httpx.ReadTimeout("Gateway timed out", request=request)
        return httpx.Response(case["expected"])

    use_mock_gateway(monkeypatch, handler)
    results = fuzz_runner.run_fuzz_suite("http://127.0.0.1:8000")
    assert results[0]["actual"] is None
    assert not results[0]["passed"]
    assert "timed out" in results[0]["error"]
    assert len(results) == 10
    for result in results[1:]:
        assert result["passed"], result["name"]
