"""
Admin auth.

Single seeded admin user (from settings.admin_username / admin_password).
Issue a session cookie or token on successful login. Provide a FastAPI
dependency (e.g. require_admin) that other admin routes can depend on
to reject unauthenticated requests.

"""
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.core.config import settings
import secrets
import time
from pydantic import BaseModel, Field

router = APIRouter()

security_scheme = HTTPBearer(auto_error=False)

ACTIVE_SESSIONS: dict[str, dict] = {}
SESSION_LIFETIME_SECONDS = 3600

class LoginRequest(BaseModel):
    username: str = Field(..., description="The user's account username")
    password: str = Field(..., description="The account password")

@router.post("/login")
def login(login_data: LoginRequest, response: Response):
    username = login_data.username
    password = login_data.password

    if username != settings.admin_username or password != settings.admin_password:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # issue a session token/cookie here
    session_token = secrets.token_hex(32)
    ACTIVE_SESSIONS[session_token] = {
        "username": username,
        "is_admin": True,
        "expires_at": time.time() + SESSION_LIFETIME_SECONDS
    }
    return {
        "status": "successfully logged in",
        "access_token": session_token,
        "token_type": "bearer"
    }


def require_admin(credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme)) -> dict:    
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token."
        )

    token = credentials.credentials
    session_data = ACTIVE_SESSIONS.get(token)
    
    if not session_data:
        raise HTTPException(
            status_code=401,
            detail="Invalid token or session expired.",
        )
        
    if time.time() > session_data.get("expires_at", 0):
        ACTIVE_SESSIONS.pop(token, None)
        raise HTTPException(
            status_code=401,
            detail="Token has expired. Please log in again.",
        )

    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid token or session expired.",
        )
    
    # if not session_data.get("is_admin", False):
    #     raise HTTPException(
    #         status_code=403,
    #         detail="Access forbidden. Administrator privileges required.",
    #     )
        
    return session_data
