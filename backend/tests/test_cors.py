import pytest
from fastapi.testclient import TestClient
from main import app


client = TestClient(app)


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:9000",
        "https://localhost",
    ],
)
def test_login_preflight_allows_any_localhost_port(origin):
    response = client.options(
        "/admin/login",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert response.headers["access-control-allow-credentials"] == "true"
    assert "POST" in response.headers["access-control-allow-methods"]
    allowed_headers = response.headers["access-control-allow-headers"].casefold()
    assert "content-type" in allowed_headers


def test_preflight_rejects_unconfigured_origin():
    response = client.options(
        "/admin/login",
        headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_preflight_rejects_similar_non_localhost_hostname():
    response = client.options(
        "/admin/login",
        headers={
            "Origin": "http://localhost.attacker.example:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
