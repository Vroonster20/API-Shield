"""
[Task B09] Admin API.

Endpoints the dashboard calls. All require app.routes.auth.require_admin:

  GET  /admin/logs        -- recent requests_log rows
  GET  /admin/bans        -- current bans
  POST /admin/bans        -- manually ban an IP
  DELETE /admin/bans/{id} -- revoke a ban
  GET  /admin/settings    -- current rate limit / ban duration config
  PUT  /admin/settings    -- update config
  POST /admin/fuzz        -- run the fuzz suite (see app/fuzzing/fuzz_runner.py)
"""
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Path,
    Query,
    Response,
    status,
)
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, IPvAnyAddress
from app.core.config import settings
from app.db.database import (
    get_recent_logs, delete_ban, get_current_bans, get_rules, save_rules,
)
from app.fuzzing.fuzz_runner import run_fuzz_suite
from app.routes.auth import require_admin
from app.security.ban_manager import ban_ip

router = APIRouter(
    dependencies=[Depends(require_admin)],
)

class BanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ip: IPvAnyAddress


class SettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rate_limit_requests: int = Field(strict=True, ge=1, le=10000)
    rate_limit_window_seconds: int = Field(strict=True, ge=1, le=86400)
    ban_duration_seconds: int = Field(strict=True, ge=1, le=604800)


def apply_settings(values: SettingsRequest):
    settings.rate_limit_requests = values.rate_limit_requests
    settings.rate_limit_window_seconds = values.rate_limit_window_seconds
    settings.ban_duration_seconds = values.ban_duration_seconds


def load_saved_settings():
    values = get_settings()
    saved = get_rules()
    for key in values:
        if key in saved:
            values[key] = int(saved[key])
    apply_settings(SettingsRequest(**values))


@router.get("/logs")
def list_logs(limit: int = Query(default=50, ge=1, le=500)):
    rows = get_recent_logs(limit)
    return {"logs": [dict(row) for row in rows]}


@router.get("/bans")
def list_bans():
    now = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    return {"bans": [dict(row) for row in get_current_bans(now)]}


@router.post("/bans", status_code=201)
def create_ban(body: BanRequest):
    ip = str(body.ip)
    ban_ip(ip)

    return {
        "status": "banned",
        "ip": ip,
    }

@router.delete(
    "/bans/{ban_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def revoke_ban(ban_id: int = Path(..., gt=0)) -> Response:
    deleted = delete_ban(ban_id)

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ban not found",
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/settings")
def get_settings():
    return {
        "rate_limit_requests": settings.rate_limit_requests,
        "rate_limit_window_seconds": settings.rate_limit_window_seconds,
        "ban_duration_seconds": settings.ban_duration_seconds,
    }


@router.put("/settings")
def update_settings(body: SettingsRequest):
    save_rules(body.model_dump())
    apply_settings(body)
    return get_settings()


@router.post("/fuzz")
def run_fuzz():
    # The demo gateway runs locally on port 8000, separately from the target.
    results = run_fuzz_suite("http://127.0.0.1:8000")
    return {
        "results": results,
        "passed": sum(result["passed"] for result in results),
        "total": len(results),
    }
