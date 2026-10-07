"""
[Task B06] Security event logging.

One function, called from the gateway on every request (allowed or
blocked), that writes a row to requests_log.
"""
from datetime import datetime, timezone

from app.db.database import get_db


def log_event(ip: str, path: str, decision: str, reason: str | None = None) -> None:
    """
    decision: 'allowed' | 'blocked'
    reason:   e.g. 'rate_limit', 'banned', 'invalid_input' -- None if allowed
    """
    with get_db() as conn:
        conn.execute(
            "INSERT INTO requests_log (timestamp, ip, path, decision, reason) "
            "VALUES (?, ?, ?, ?, ?)",
            (datetime.now(timezone.utc).isoformat(), ip, path, decision, reason),
        )
