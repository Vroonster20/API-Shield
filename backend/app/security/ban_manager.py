"""
[Task B04] Ban management.

Check/add bans by IP, stored in the `bans` table (see db/database.py).
A ban is "active" if expires_at is in the future.
"""
from app.db.database import get_db

# TODO [B04]: implement using get_db() and simple SQL, e.g.:
#
# def is_banned(ip: str) -> bool:
#     with get_db() as conn:
#         row = conn.execute(
#             "SELECT 1 FROM bans WHERE ip = ? AND expires_at > ? LIMIT 1",
#             (ip, now_iso),
#         ).fetchone()
#         return row is not None


def is_banned(ip: str) -> bool:
    raise NotImplementedError


def ban_ip(ip: str) -> None:
    """Ban an IP for settings.ban_duration_seconds from now."""
    raise NotImplementedError
