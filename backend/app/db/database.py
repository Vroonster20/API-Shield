"""
[Task B01] Database layer — plain sqlite3, no ORM.

Tables:
  - requests_log: every request the gateway sees (allowed or blocked)
  - bans:         currently/previously banned IPs
  - rules:        configurable settings (rate limit, ban duration) -- optional,
                   may just read from app.core.config instead if you don't need
                   runtime-editable settings for the demo.
"""
import sqlite3
from contextlib import contextmanager

from app.core.config import settings


@contextmanager
def get_db():
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def create_tables():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS requests_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                ip TEXT NOT NULL,
                path TEXT NOT NULL,
                decision TEXT NOT NULL,   -- 'allowed' | 'blocked'
                reason TEXT               -- e.g. 'rate_limit', 'banned', 'invalid_input', NULL if allowed
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip TEXT NOT NULL,
                banned_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rules (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)


# TODO [B01]: add small helper functions as needed, e.g.:
#   insert_log(ip, path, decision, reason)
#   insert_ban(ip, banned_at, expires_at)
#   get_active_ban(ip)
# Keep these here so other modules don't write raw SQL everywhere.
