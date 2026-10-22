"""
[Task B01] Database layer — plain sqlite3, no ORM.

Tables:
  - requests_log: every request the gateway sees (allowed or blocked)
  - bans:         currently/previously banned IPs
  - rules:        configurable settings (rate limit, ban duration) -- optional,
                   may just read from app.core.config instead if you don't need
                   runtime-editable settings for the demo.
"""
from datetime import datetime, timedelta, timezone
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
                reason TEXT,              -- e.g. 'rate_limit', 'banned', 'invalid_input', NULL if allowed
                source TEXT NOT NULL DEFAULT 'live'
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip TEXT NOT NULL,
                banned_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'live'
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rules (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS app_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        _ensure_column(conn, "requests_log", "source", "TEXT NOT NULL DEFAULT 'live'")
        _ensure_column(conn, "bans", "source", "TEXT NOT NULL DEFAULT 'live'")


def _ensure_column(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    columns = {
        row["name"] for row in conn.execute(f"PRAGMA table_info({table})")
    }
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def seed_demo_data() -> bool:
    """Populate an empty database once with clearly labeled sample activity."""
    now = datetime.now(timezone.utc)
    with get_db() as conn:
        inserted_marker = conn.execute(
            "INSERT OR IGNORE INTO app_metadata (key, value) "
            "VALUES ('demo_data_seeded', 'true')"
        )
        if inserted_marker.rowcount == 0:
            return False

        has_existing_data = any(
            conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
            for table in ("requests_log", "bans")
        )
        if has_existing_data:
            return False

        log_examples = (
            (now - timedelta(minutes=2), "192.0.2.24", "/login", "allowed", None),
            (
                now - timedelta(minutes=5),
                "198.51.100.37",
                "/orders/42",
                "blocked",
                "rate_limit",
            ),
            (
                now - timedelta(minutes=11),
                "203.0.113.56",
                "/webhooks/payments",
                "blocked",
                "invalid_input",
            ),
            (
                now - timedelta(minutes=18),
                "192.0.2.81",
                "/db/orders",
                "blocked",
                "upstream_timeout",
            ),
            (
                now - timedelta(minutes=24),
                "198.51.100.42",
                "/orders/17",
                "blocked",
                "banned",
            ),
        )
        conn.executemany(
            "INSERT INTO requests_log "
            "(timestamp, ip, path, decision, reason, source) "
            "VALUES (?, ?, ?, ?, ?, 'demo')",
            [
                (timestamp.isoformat(timespec="microseconds"), ip, path, decision, reason)
                for timestamp, ip, path, decision, reason in log_examples
            ],
        )

        ban_examples = (
            ("198.51.100.42", 10, 3600),
            ("203.0.113.17", 15, 7200),
        )
        conn.executemany(
            "INSERT INTO bans (ip, banned_at, expires_at, source) "
            "VALUES (?, ?, ?, 'demo')",
            [
                (
                    ip,
                    (now - timedelta(minutes=minutes_ago)).isoformat(
                        timespec="microseconds"
                    ),
                    (now + timedelta(seconds=seconds_remaining)).isoformat(
                        timespec="microseconds"
                    ),
                )
                for ip, minutes_ago, seconds_remaining in ban_examples
            ],
        )
    return True


def insert_ban(
    ip: str,
    banned_at: str,
    expires_at: str,
    source: str = "live",
) -> int:
    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO bans (ip, banned_at, expires_at, source) "
            "VALUES (?, ?, ?, ?)",
            (ip, banned_at, expires_at, source),
        )
        return cursor.lastrowid

def get_ban(ban_id: int):
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM bans WHERE id = ?",
            (ban_id,),
        ).fetchone()

def get_active_ban(ip: str, now_iso:str):
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM bans WHERE ip = ? AND expires_at > ? "
            "ORDER BY expires_at DESC LIMIT 1",
            (ip, now_iso)
        ).fetchone()

def get_active_bans(now_iso: str):
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM bans WHERE expires_at > ? ORDER BY expires_at DESC",
            (now_iso,),
        ).fetchall()

def delete_ban(ban_id: int) -> bool:
    with get_db() as conn:
        cursor = conn.execute("DELETE FROM bans WHERE id = ?", (ban_id,))
        return cursor.rowcount > 0

def get_recent_logs(limit: int = 50):
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM requests_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()

def get_rules() -> dict[str, str]:
    with get_db() as conn:
        rows = conn.execute("SELECT key, value FROM rules").fetchall()
        return {row["key"]: row["value"] for row in rows}

def save_rules(values: dict[str, int]) -> None:
    with get_db() as conn:
        conn.executemany(
            "INSERT INTO rules (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            [(key, str(value)) for key, value in values.items()],
        )
