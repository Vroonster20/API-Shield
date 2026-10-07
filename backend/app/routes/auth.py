"""
[Task B08] Admin auth.

Single seeded admin user (from settings.admin_username / admin_password).
Issue a session cookie or token on successful login. Provide a FastAPI
dependency (e.g. require_admin) that other admin routes can depend on
to reject unauthenticated requests.

Doesn't need production-grade hashing/CSRF for this project -- just
needs to not be wide open.
"""
from fastapi import APIRouter, HTTPException

router = APIRouter()

# TODO [B08]:
# @router.post("/login")
# def login(username: str, password: str):
#     if username != settings.admin_username or password != settings.admin_password:
#         raise HTTPException(status_code=401, detail="Invalid credentials")
#     # issue a session token/cookie here
#
# def require_admin(...):
#     """FastAPI dependency: raise 401 if no valid session."""
#     raise NotImplementedError
