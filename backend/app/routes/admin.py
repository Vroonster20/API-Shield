"""
Admin API.
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
from app.fuzzing.fuzz_runner import run_fuzz_suite
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


def current_settings() -> dict[str, int]:
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
    now = datetime.now().isoformat(timespec="microseconds")
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
    return current_settings()


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


@router.post("/fuzz")
async def fuzz_gateway(
    _: dict = Depends(require_admin),
):
    return await run_fuzz_suite(settings.gateway_base_url)
