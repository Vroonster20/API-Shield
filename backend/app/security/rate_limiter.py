"""
[Task B03] Rate limiting.

Fixed-window limiter: count requests per IP within the current window
(app.core.config.settings.rate_limit_window_seconds). Reject once the
count exceeds rate_limit_requests.

Simplest approach: an in-memory dict of {ip: (window_start, count)}.
Fine for a single-process demo; doesn't need to survive restarts.
"""
from app.core.config import settings
import time

_counts: dict[str, list[float]] = {}

def is_allowed(ip: str) -> bool:
    limit = settings.rate_limit_requests
    window = settings.rate_limit_window_seconds

    current_time = time.time()

    if ip not in _counts:
        _counts[ip] = []
    
    counts = _counts[ip]

    while counts and counts[0] <= current_time - window:
        counts.pop(0)

    if len(counts) < limit:
        counts.append(current_time)
        return True

    return False