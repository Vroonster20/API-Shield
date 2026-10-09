"""
[Task B02] Separate, minimal DB for the fake target app -- intentionally
not shared with the gateway's db/database.py. Keeps the target fully
independent, as a real protected app would be.
"""
import sqlite3
from contextlib import contextmanager
from faker import Faker
import pandas as pd


@contextmanager
def get_target_db():
    conn = sqlite3.connect("./backend/target/target_db.db")
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
    df = pd.read_csv("./backend/target/source_files/orders.csv")
    df = df.drop(columns=['Delivery Date', 'Cost Price Per Unit'])
    with get_target_db() as conn:
        df.to_sql("orders",conn, if_exists='replace', index=False)
    
def fill_user_table():
    fake = Faker()
    fake_pass = '$2b$12$ssx98mIQ6enMuhSjQWgiUOEc0lcEfxpSeQND5HTckfkVku6yvx/AC'
    with get_target_db() as conn:
        for i in range(1,10):
            fake_user = fake.user_name()
            user_data = (fake_user,fake_pass)
            conn.execute("INSERT INTO users (username,password) VALUES (?,?)", user_data)
            conn.commit()

# test to make sure tables are set up correctly
def test_user_table():
    with get_target_db() as conn:
        rows = conn.execute("SELECT * FROM users")
        for row in rows:
            print(row)

def test_orders_table():
    with get_target_db() as conn:
        rows = conn.execute('SELECT "Customer ID" FROM orders WHERE "Customer Status"=="Silver"')
        for row in rows:
            print(row)


# TODO [B02]: optionally seed a demo user here for testing.