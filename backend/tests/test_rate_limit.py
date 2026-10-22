"""
Tests for the rate limiter.
"""
from app.security.rate_limiter import is_allowed
from app.core.config import settings
from unittest.mock import patch

limit = settings.rate_limit_requests
window = settings.rate_limit_window_seconds

def test_allows_requests_under_the_limit():
    test_ip = "192.168.1.10"
    i = 1

    for _ in range(limit):
        assert is_allowed(test_ip) is True, f"Request {i} should be allowed"
        i += 1


def test_rejects_request_over_the_limit():
    test_ip = "192.168.2.20"
    i = 1

    for _ in range(limit):
        assert is_allowed(test_ip) is True, f"Request {i} should be allowed"
        i += 1

    assert is_allowed(test_ip) is False, f"Request shouldn't be allowed"

@patch("time.time")
def test_resets_after_window_expires(mock_time):
    current_mock_time = 1000.0
    mock_time.return_value = current_mock_time

    test_ip = "192.168.3.30"
    i = 1
    
    for _ in range(limit):
        assert is_allowed(test_ip) is True, f"Request {i} should be allowed"
        i += 1

    assert is_allowed(test_ip) is False, f"Request shouldn't be allowed"

    current_mock_time += window // 2
    mock_time.return_value = current_mock_time

    assert is_allowed(test_ip) is False, f"Request shouldn't be allowed"

    # testing a second ip ensuring it's allowed
    second_test_ip = "192.168.4.40"
    assert is_allowed(second_test_ip) is True, f"Request should be allowed"

    current_mock_time += window // 2 + 1
    mock_time.return_value = current_mock_time

    assert is_allowed(test_ip) is True, f"Request should be allowed"

    for _ in range(limit - 1):
            assert is_allowed(test_ip) is True, f"Request {i} should be allowed"
            i += 1
    
    assert is_allowed(test_ip) is False, f"Request shouldn't be allowed"