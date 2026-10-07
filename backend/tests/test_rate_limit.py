"""
[Task B03] Tests for the rate limiter.
Write these BEFORE or WHILE implementing rate_limiter.py -- they define
what "done" means for this task.
"""
# from app.security.rate_limiter import is_allowed


def test_allows_requests_under_the_limit():
    # TODO: call is_allowed() N times (N = rate_limit_requests), all should be True
    pass


def test_rejects_request_over_the_limit():
    # TODO: the (N+1)th request in the same window should return False
    pass


def test_resets_after_window_expires():
    # TODO: simulate time passing, confirm the count resets
    pass
