"""
[Task B02] Fake target API -- the app being "protected."

This is a small, standalone FastAPI app with its own DB. It knows
nothing about the gateway -- it just behaves like a real app would.
The gateway (app/routes/gateway.py) forwards approved requests here.

Run standalone with:
    uvicorn target.target_main:app --reload --port 8001

Suggested endpoints to implement (adjust to taste):
    POST /login   -- check username/password against a users table
    GET  /orders  -- list orders for a user
    POST /orders  -- place an order (product_id, quantity)

Keep this intentionally simple -- it's a demo target, not the project
being graded.
"""
from fastapi import FastAPI

from target.target_db import create_target_tables

app = FastAPI(title="Fake Target API")


@app.on_event("startup")
def on_startup():
    create_target_tables()


@app.get("/health")
def health():
    return {"status": "ok"}


# TODO [B02]: add /login, /orders (or whatever endpoints fit your demo),
# matching whatever Pydantic models you define in app/security/validator.py.
