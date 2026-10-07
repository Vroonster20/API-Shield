"""
[Task B03] Rate limiting.

Fixed-window limiter: count requests per IP within the current window
(app.core.config.settings.rate_limit_window_seconds). Reject once the
count exceeds rate_limit_requests.

Simplest approach: an in-memory dict of {ip: (window_start, count)}.
Fine for a single-process demo; doesn't need to survive restarts.
"""
from app.core.config import settings

# TODO [B03]: replace with real tracking, e.g.:
# _counts: dict[str, tuple[float, int]] = {}


def is_allowed(ip: str) -> bool:
    """Return True if this request should be allowed, False if rate-limited."""
    raise NotImplementedError
