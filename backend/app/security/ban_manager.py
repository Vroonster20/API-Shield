"""
Ban management.

Check/add bans by IP, stored in the `bans` table (see db/database.py).
A ban is "active" if expires_at is in the future.
"""
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.db.database import get_active_ban, insert_ban



def is_banned(ip: str) -> bool:
    """Return whether the IP has an unexpired ban."""
    now_iso = datetime.now().isoformat(timespec="microseconds")
    return get_active_ban(ip, now_iso) is not None


def ban_ip(ip: str) -> int:
    """Ban an IP for settings.ban_duration_seconds from now."""
    now = datetime.now()
    expires_at = now + timedelta(seconds=settings.ban_duration_seconds)
    return insert_ban(
        ip,
        now.isoformat(timespec="microseconds"),
        expires_at.isoformat(timespec="microseconds"),
    )
