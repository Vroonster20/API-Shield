"""
 SQLite3 Database layer

Tables:
  - requests_log: every request the gateway sees (allowed or blocked)
  - bans:         currently/previously banned IPs
  - rules:        configurable settings (rate limit, ban duration)
"""
from datetime import datetime, timedelta, timezone
import sqlite3
from contextlib import contextmanager
from collections.abc import Generator

from app.core.config import settings


@contextmanager
def get_db() -> Generator[sqlite3.Connection]:
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
                decision TEXT NOT NULL,  
                reason TEXT,              
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
        ensure_column(conn, "requests_log", "source", "TEXT NOT NULL DEFAULT 'live'")
        ensure_column(conn, "bans", "source", "TEXT NOT NULL DEFAULT 'live'")


def ensure_column(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    columns = set()
    for row in conn.execute(f"PRAGMA table_info({table})"):
        columns.add(row["name"])
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
    banned_at = normalize_timestamp(banned_at)
    expires_at = normalize_timestamp(expires_at)
    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO bans (ip, banned_at, expires_at, source) "
            "VALUES (?, ?, ?, ?)",
            (ip, banned_at, expires_at, source),
        )
        return cursor.lastrowid


def normalize_timestamp(value: str) -> str:
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    return parsed.isoformat(timespec="microseconds")

def get_ban(ban_id: int):
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM bans WHERE id = ?",
            (ban_id,),
        ).fetchone()

def get_active_ban(ip: str, now_iso:str):
    now = parse_timestamp(now_iso)
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM bans WHERE ip = ?",
            (ip,),
        ).fetchall()
    active = [
        row
        for row in rows
        if parse_timestamp(row["expires_at"]) > now
    ]
    if not active:
        return None
    return max(active, key=lambda row: parse_timestamp(row["expires_at"]))

def get_active_bans(now_iso: str):
    now = parse_timestamp(now_iso)
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM bans").fetchall()
    active = [
        row
        for row in rows
        if parse_timestamp(row["expires_at"]) > now
    ]
    return sorted(
        active,
        key=lambda row: parse_timestamp(row["expires_at"]),
        reverse=True,
    )


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)

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
