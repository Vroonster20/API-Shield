"""
[Task B02] Separate, minimal DB for the fake target app -- intentionally
not shared with the gateway's db/database.py. Keeps the target fully
independent, as a real protected app would be.
"""
import sqlite3
from contextlib import contextmanager

TARGET_DB_PATH = "target.db"


@contextmanager
def get_target_db():
    conn = sqlite3.connect(TARGET_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def create_target_tables():
    with get_target_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL
            )
        """)

# TODO [B02]: optionally seed a demo user here for testing.
