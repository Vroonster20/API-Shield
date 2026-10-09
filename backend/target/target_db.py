"""
[Task B02] Separate, minimal DB for the fake target app -- intentionally
not shared with the gateway's db/database.py. Keeps the target fully
independent, as a real protected app would be.
"""
import sqlite3
from contextlib import contextmanager
from faker import Faker


@contextmanager
def get_target_db():
    conn = sqlite3.connect("target_db.db")
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
                date_of_order TEXT NOT NULL,
                product_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                total_price DOUBLE NOT NULL
            )
        """)
def fill_user_table():
    fake = Faker()
    fake_pass = '$2b$12$ssx98mIQ6enMuhSjQWgiUOEc0lcEfxpSeQND5HTckfkVku6yvx/AC'
    with get_target_db() as conn:
        for i in range(1,10):
            fake_user = fake.user_name()
            user_data = (fake_user,fake_pass)
            conn.execute("INSERT INTO users (username,password) VALUES (?,?)", user_data)
            conn.commit()

def test_user_table():
    with get_target_db() as conn:
        rows = conn.execute("SELECT * FROM users")
        for row in rows:
            print(row)

def fill_order_table():
    pass


# TODO [B02]: optionally seed a demo user here for testing.