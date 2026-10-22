"""
[Task B09] Admin API.

Endpoints the dashboard will call -- all should depend on
app.routes.auth.require_admin (once B08 is implemented):

  GET  /admin/logs        -- recent requests_log rows
  GET  /admin/bans        -- current bans
  POST /admin/bans        -- manually ban an IP
  DELETE /admin/bans/{id} -- revoke a ban
  GET  /admin/settings    -- current rate limit / ban duration config
  PUT  /admin/settings    -- update config
  POST /admin/fuzz        -- run the fuzz suite (see app/fuzzing/fuzz_runner.py)
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, IPvAnyAddress

from app.core.config import settings
from app.db.database import (
    delete_ban,
    get_active_bans,
    get_ban,
    get_recent_logs,
    get_rules,
    save_rules,
)
from app.routes.auth import require_admin
from app.security.ban_manager import ban_ip

router = APIRouter()


class BanRequest(BaseModel):
    ip: IPvAnyAddress


class SettingsUpdate(BaseModel):
    rate_limit_requests: int = Field(gt=0, strict=True)
    rate_limit_window_seconds: int = Field(gt=0, strict=True)
    ban_duration_seconds: int = Field(gt=0, strict=True)


SETTING_KEYS = (
    "rate_limit_requests",
    "rate_limit_window_seconds",
    "ban_duration_seconds",
)


def _current_settings() -> dict[str, int]:
    saved_rules = get_rules()
    values: dict[str, int] = {}
    for key in SETTING_KEYS:
        if key in saved_rules:
            value = int(saved_rules[key])
            if value < 1:
                raise ValueError(f"Stored setting {key} must be greater than zero.")
            setattr(settings, key, value)
        values[key] = getattr(settings, key)
    return values


@router.get("/logs")
def list_logs(_: dict = Depends(require_admin)):
    return [dict(row) for row in get_recent_logs()]


@router.get("/bans")
def list_bans(_: dict = Depends(require_admin)):
    now = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    return [
        {**dict(row), "status": "active"}
        for row in get_active_bans(now)
    ]


@router.post("/bans", status_code=status.HTTP_201_CREATED)
def create_ban(
    ban: BanRequest,
    _: dict = Depends(require_admin),
):
    ip = str(ban.ip)
    ban_id = ban_ip(ip)
    created = get_ban(ban_id)
    if created is None:
        raise RuntimeError("The newly created ban could not be loaded.")
    return {**dict(created), "status": "active"}


@router.delete("/bans/{ban_id}")
def revoke_ban(ban_id: int, _: dict = Depends(require_admin)):
    if not delete_ban(ban_id):
        raise HTTPException(status_code=404, detail="Ban not found.")
    return {"status": "success"}


@router.get("/settings")
def read_settings(_: dict = Depends(require_admin)):
    return _current_settings()


@router.put("/settings")
def update_settings(
    values: SettingsUpdate,
    _: dict = Depends(require_admin),
):
    updated = values.model_dump()
    save_rules(updated)
    for key, value in updated.items():
        setattr(settings, key, value)
    return updated
