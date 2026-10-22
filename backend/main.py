"""
[Task B00] App entry point.

Run with: uvicorn main:app --reload
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
import uvicorn

from app.db.database import create_tables
from app.routes import gateway, auth, admin   # uncomment as each router is implemented

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    admin.load_saved_settings()
    yield

app = FastAPI(title="API-Shield", lifespan=lifespan)

@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(gateway.router)
app.include_router(auth.router, prefix="/admin")
app.include_router(admin.router, prefix="/admin")

if __name__ == "__main__":
    uvicorn.run(app, port=8000, reload=True)
