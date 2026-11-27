"""
App configuration, loaded from environment variables (.env).
"""
from pydantic_settings import BaseSettings
from pydantic import SecretStr, field_validator

class Settings(BaseSettings):
    db_path: str = "shield.db"
    seed_demo_data: bool = True

    rate_limit_requests: int = 10
    rate_limit_window_seconds: int = 60

    ban_duration_seconds: int = 300

    target_api_url: str = "http://127.0.0.1:8001"
    gateway_base_url: str = "http://127.0.0.1:8000"

    admin_username: str = "admin"
    admin_password: str

    @field_validator("admin_password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 12:
            raise ValueError("admin_password must be at least 12 characters long")
        if v.lower() in {"password", "admin", "changeme"}:
            raise ValueError("admin_password cannot be a common placeholder")
        return v

    cors_allowed_origin_regex: str = (
        r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"
    )


    class Config:
        env_file=".env"
        env_file_encoding="utf-8"
        extra="ignore"


settings = Settings()
