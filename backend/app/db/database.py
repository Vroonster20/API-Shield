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

def insert_ban(ip: str, banned_at: str, expires_at: str) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO bans (ip, banned_at, expires_at) VALUES (?, ?, ?)", 
            (ip, banned_at, expires_at)
        )

def get_active_ban(ip: str, now_iso:str):
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM bans WHERE ip = ? AND expires_at > ? "
            "ORDER BY expires_at DESC LIMIT 1",
            (ip, now_iso)
        ).fetchone()

def get_recent_logs(limit: int = 50):
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM requests_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()


def get_current_bans(now_iso: str):
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM bans WHERE expires_at > ? ORDER BY id DESC",
            (now_iso,),
        ).fetchall()


def delete_ban(ban_id: int) -> bool:
    with get_db() as conn:
        result = conn.execute("DELETE FROM bans WHERE id = ?", (ban_id,))
        return result.rowcount > 0


def get_rules() -> dict:
    with get_db() as conn:
        rows = conn.execute("SELECT key, value FROM rules").fetchall()
        return {row["key"]: row["value"] for row in rows}


def save_rules(values: dict):
    with get_db() as conn:
        for key, value in values.items():
            conn.execute(
                "INSERT OR REPLACE INTO rules (key, value) VALUES (?, ?)",
                (key, str(value)),
            )
