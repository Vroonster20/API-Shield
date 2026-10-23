"""
App entry point.

Run with: uvicorn main:app --reload
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from app.core.config import settings
from app.db.database import create_tables, get_rules, seed_demo_data
from app.routes import gateway, auth, admin

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    if settings.seed_demo_data:
        seed_demo_data()
    saved_rules = get_rules()
    for key in ("rate_limit_requests", "rate_limit_window_seconds", "ban_duration_seconds"):
        if key in saved_rules:
            value = int(saved_rules[key])
            if value < 1:
                raise ValueError(f"Stored setting {key} must be greater than zero.")
            setattr(settings, key, value)
    yield

app = FastAPI(title="API-Shield", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=settings.cors_allowed_origin_regex,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(gateway.router, prefix="/gateway")
app.include_router(auth.router, prefix="/admin")
app.include_router(admin.router, prefix="/admin")

if __name__ == "__main__":
    uvicorn.run("main:app", port=8000, reload=True)