"""Synthetic course demo. Its application database is separate from Shield state."""

from __future__ import annotations

import asyncio
import hashlib
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    username: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class CartItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    product_id: str = Field(min_length=1, max_length=64)
    quantity: int = Field(ge=1, le=99)


class Booking(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    resource: str = Field(min_length=1, max_length=80)
    seats: int = Field(ge=1, le=8)


PAGE = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Shield demo storefront</title>
<style>body{font:17px system-ui;max-width:760px;margin:3rem auto;padding:1rem;background:#f2f5fa;color:#13243d}section{background:white;padding:1.5rem;margin:1rem 0;border-radius:12px}label{display:block;margin:.8rem 0}input,button{font:inherit;padding:.5rem}pre{white-space:pre-wrap;overflow-wrap:anywhere}button{cursor:pointer}</style>
<h1>Shield demo storefront</h1><p>Synthetic data only. This page and its API pass through the same gateway.</p>
<section><h2>1. Register and sign in</h2><label>Username <input id="user" autocomplete="username"></label>
<label>Password (12–128 characters for signup) <input id="pass" type="password" autocomplete="current-password"></label>
<button id="register">Register</button> <button id="login">Sign in</button></section>
<section><h2>2. Try the cart</h2><button id="products">List products</button> <button id="add">Add one notebook</button> <button id="cart">View my cart</button></section>
<section><h2>3. Try another API type</h2><button id="book">Reserve one workshop seat</button></section>
<section aria-live="polite"><h2>Response</h2><pre id="out">Ready.</pre></section>
<script>
async function call(path,body){const r=await fetch(path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});document.querySelector('#out').textContent=r.status+' '+await r.text()}
for(const action of ['register','login'])document.querySelector('#'+action).onclick=()=>call('/auth/'+action,{username:document.querySelector('#user').value,password:document.querySelector('#pass').value});
document.querySelector('#products').onclick=()=>call('/products');document.querySelector('#cart').onclick=()=>call('/cart/items');
document.querySelector('#add').onclick=()=>call('/cart/items',{product_id:'notebook',quantity:1});document.querySelector('#book').onclick=()=>call('/reservations',{resource:'workshop',seats:1});
</script></html>"""


def create_demo(database_path: Path) -> FastAPI:
    hasher = PasswordHasher(time_cost=2, memory_cost=19_456, parallelism=1)
    hash_slots = asyncio.Semaphore(2)
    db_lock = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(app):
        database_path.parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(database_path)
        conn.row_factory = aiosqlite.Row
        await conn.executescript("""
            CREATE TABLE IF NOT EXISTS users(username TEXT PRIMARY KEY,password_hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,username TEXT NOT NULL,expires_ms INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS products(id TEXT PRIMARY KEY,name TEXT NOT NULL,price_cents INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS cart(id TEXT PRIMARY KEY,username TEXT NOT NULL,product_id TEXT NOT NULL,quantity INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS reservations(id TEXT PRIMARY KEY,username TEXT NOT NULL,resource TEXT NOT NULL,seats INTEGER NOT NULL);
            INSERT OR IGNORE INTO products VALUES('notebook','Notebook',500);
            INSERT OR IGNORE INTO products VALUES('pen','Pen',150);
        """)
        await conn.commit()
        app.state.db = conn
        app.state.receipts = 0  # Private runner inspection; no public reset/inspection endpoint.
        app.state.dummy_hash = await asyncio.to_thread(hasher.hash, secrets.token_urlsafe(24))
        try:
            yield
        finally:
            await conn.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def receipt(request: Request, call_next):
        app.state.receipts += 1
        if (
            request.method == "POST"
            and request.headers.get("content-type", "").split(";")[0] != "application/json"
        ):
            return JSONResponse({"detail": "JSON required"}, status_code=415)
        return await call_next(request)

    async def user(request):
        token = request.cookies.get("demo_session", "")
        if len(token) > 128:
            raise HTTPException(401, "Sign in required")
        digest = hashlib.sha256(token.encode()).hexdigest()
        row = await (
            await app.state.db.execute(
                "SELECT username FROM sessions WHERE token_hash=? AND expires_ms>?",
                (digest, int(time.time() * 1000)),
            )
        ).fetchone()
        if not row:
            raise HTTPException(401, "Sign in required")
        return row["username"]

    @app.get("/", response_class=HTMLResponse)
    async def home():
        return PAGE

    @app.post("/auth/register", status_code=201)
    async def register(body: Credentials):
        if len(body.password) < 12:
            raise HTTPException(422, "Password must have at least 12 characters")
        async with hash_slots:
            password_hash = await asyncio.to_thread(hasher.hash, body.password)
        async with db_lock:
            try:
                await app.state.db.execute("INSERT INTO users VALUES(?,?)", (body.username, password_hash))
                await app.state.db.commit()
            except aiosqlite.IntegrityError:
                await app.state.db.rollback()
                raise HTTPException(409, "Username unavailable") from None
        return {"created": True}

    @app.post("/auth/login")
    async def login(body: Credentials):
        row = await (
            await app.state.db.execute("SELECT password_hash FROM users WHERE username=?", (body.username,))
        ).fetchone()
        async with hash_slots:
            try:
                await asyncio.to_thread(
                    hasher.verify, row["password_hash"] if row else app.state.dummy_hash, body.password
                )
                valid = row is not None
            except VerificationError:
                valid = False
        if not valid:
            raise HTTPException(401, "Invalid credentials")
        token = secrets.token_urlsafe(32)
        async with db_lock:
            await app.state.db.execute("DELETE FROM sessions WHERE expires_ms<=?", (int(time.time() * 1000),))
            await app.state.db.execute(
                "INSERT INTO sessions VALUES(?,?,?)",
                (
                    hashlib.sha256(token.encode()).hexdigest(),
                    body.username,
                    int(time.time() * 1000) + 3_600_000,
                ),
            )
            await app.state.db.commit()
        response = JSONResponse({"signed_in": True})
        response.set_cookie("demo_session", token, httponly=True, samesite="strict", max_age=3600)
        return response

    @app.api_route("/products", methods=["GET", "HEAD"])
    async def products(request: Request):
        rows = await (await app.state.db.execute("SELECT * FROM products ORDER BY id")).fetchall()
        return (
            Response(status_code=200) if request.method == "HEAD" else {"items": [dict(row) for row in rows]}
        )

    @app.get("/cart/items")
    async def cart(request: Request):
        owner = await user(request)
        rows = await (
            await app.state.db.execute(
                "SELECT c.id,c.product_id,c.quantity,p.price_cents,c.quantity*p.price_cents AS total_cents FROM cart c JOIN products p ON p.id=c.product_id WHERE username=? ORDER BY c.id",
                (owner,),
            )
        ).fetchall()
        return {"items": [dict(row) for row in rows]}

    @app.post("/cart/items", status_code=201)
    async def add_cart(request: Request, body: CartItem):
        owner = await user(request)
        async with db_lock:
            product = await (
                await app.state.db.execute("SELECT price_cents FROM products WHERE id=?", (body.product_id,))
            ).fetchone()
            if not product:
                raise HTTPException(404, "Unknown product")
            item_id = secrets.token_hex(16)
            await app.state.db.execute(
                "INSERT INTO cart VALUES(?,?,?,?)", (item_id, owner, body.product_id, body.quantity)
            )
            await app.state.db.commit()
        return {"id": item_id, "total_cents": product["price_cents"] * body.quantity}

    @app.delete("/cart/items/{item_id}", status_code=204)
    async def delete_cart(request: Request, item_id: str):
        owner = await user(request)
        async with db_lock:
            result = await app.state.db.execute(
                "DELETE FROM cart WHERE id=? AND username=?", (item_id, owner)
            )
            await app.state.db.commit()
        if result.rowcount != 1:
            raise HTTPException(404, "Item not found")
        return Response(status_code=204)

    @app.post("/reservations", status_code=201)
    async def reserve(request: Request, body: Booking):
        owner = await user(request)
        booking_id = secrets.token_hex(16)
        async with db_lock:
            await app.state.db.execute(
                "INSERT INTO reservations VALUES(?,?,?,?)", (booking_id, owner, body.resource, body.seats)
            )
            await app.state.db.commit()
        return {"id": booking_id, "reserved": body.seats}

    return app
