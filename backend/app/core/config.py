"""
[Task B00] App configuration, loaded from environment variables (.env).
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    db_path: str = "shield.db"

    rate_limit_requests: int = 10
    rate_limit_window_seconds: int = 60

    ban_duration_seconds: int = 300

    target_api_url: str = "http://127.0.0.1:8001"

    admin_username: str = "admin"
    admin_password: str = "changeme"

    class Config:
        env_file = ".env"


settings = Settings()
