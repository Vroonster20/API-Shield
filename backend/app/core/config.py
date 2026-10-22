"""
App configuration, loaded from environment variables (.env).
"""
from pydantic_settings import BaseSettings,SettingsConfigDict
from pydantic import SecretStr
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_PATH = BASE_DIR / ".env"

class Settings(BaseSettings):
    db_path: str = "shield.db"
    seed_demo_data: bool = True

    rate_limit_requests: int = 10
    rate_limit_window_seconds: int = 60

    ban_duration_seconds: int = 300

    target_api_url: str = "http://127.0.0.1:8001"
    gateway_base_url: str = "http://127.0.0.1:8000"

    admin_username: str = "admin"
    admin_password: str = "changeme"

    cors_allowed_origin_regex: str = (
        r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"
    )

    shared_secret_key: SecretStr = SecretStr("")


    class Config:
        env_file=ENV_PATH
        env_file_encoding="utf-8"
        extra="ignore"


settings = Settings()
