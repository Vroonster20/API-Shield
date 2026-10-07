"""
[Task B00] App entry point.

Run with: uvicorn main:app --reload
"""
from fastapi import FastAPI

from app.db.database import create_tables
# from app.routes import gateway, auth, admin   # uncomment as each router is implemented

app = FastAPI(title="API-Shield")


@app.on_event("startup")
def on_startup():
    create_tables()


@app.get("/health")
def health():
    return {"status": "ok"}


# app.include_router(gateway.router)
# app.include_router(auth.router, prefix="/admin")
# app.include_router(admin.router, prefix="/admin")
