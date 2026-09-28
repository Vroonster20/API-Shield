"""Operator settings, loaded explicitly rather than at import time."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit

from .contracts import Registry


class SettingsError(ValueError):
    pass


def _local_default(environ: Mapping[str, str]) -> Path:
    base = environ.get("LOCALAPPDATA") if os.name == "nt" else environ.get("XDG_STATE_HOME")
    if base:
        return Path(base) / "shield-api"
    if os.name == "nt":
        raise SettingsError("SHIELD_DATA_DIR or LOCALAPPDATA is required")
    home = environ.get("HOME")
    if not home:
        raise SettingsError("SHIELD_DATA_DIR or HOME is required")
    return Path(home) / ".local" / "state" / "shield-api"


class Settings:
    def __init__(
        self,
        *,
        data_dir: Path,
        registry_file: Path,
        admin_origin: str,
        mode: str,
        rate_secret_file: Path,
    ) -> None:
        if mode not in ("development", "production"):
            raise SettingsError("SHIELD_MODE must be development or production")
        try:
            parsed = urlsplit(admin_origin)
            parsed.port  # Validate an explicitly supplied port.
        except ValueError as exc:
            raise SettingsError("SHIELD_ADMIN_ORIGIN must be an exact origin") from exc
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
            or admin_origin != admin_origin.strip()
            or any(ord(char) < 32 for char in admin_origin)
        ):
            raise SettingsError("SHIELD_ADMIN_ORIGIN must be an exact origin")
        if parsed.netloc != parsed.netloc.lower() or parsed.hostname != parsed.hostname.lower():
            raise SettingsError("SHIELD_ADMIN_ORIGIN must use lowercase host")
        if mode == "production" and not admin_origin.startswith("https://"):
            raise SettingsError("Production admin origin requires HTTPS")
        if (
            mode == "development"
            and parsed.hostname not in ("localhost", "127.0.0.1", "::1")
            and not parsed.hostname.endswith(".localhost")
        ):
            raise SettingsError("Development admin origin must be loopback")
        self.data_dir = data_dir.expanduser().resolve()
        if any(part.lower().startswith("onedrive") for part in self.data_dir.parts):
            raise SettingsError("SHIELD_DATA_DIR must be outside OneDrive")
        self.registry_file = registry_file.expanduser().resolve()
        self.admin_origin = admin_origin
        self.mode = mode
        self.rate_secret_file = rate_secret_file.expanduser().resolve()

    @property
    def db_path(self) -> Path:
        return self.data_dir / "shield.sqlite3"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if environ is None else environ
        data_dir = Path(env["SHIELD_DATA_DIR"]) if env.get("SHIELD_DATA_DIR") else _local_default(env)
        registry = env.get("SHIELD_REGISTRY_FILE")
        origin = env.get("SHIELD_ADMIN_ORIGIN")
        if not registry or not origin:
            raise SettingsError("SHIELD_REGISTRY_FILE and SHIELD_ADMIN_ORIGIN are required")
        mode = env.get("SHIELD_MODE", "development")
        secret = (
            Path(env["SHIELD_RATE_SECRET_FILE"])
            if env.get("SHIELD_RATE_SECRET_FILE")
            else data_dir / "rate.key"
        )
        return cls(
            data_dir=data_dir,
            registry_file=Path(registry),
            admin_origin=origin,
            mode=mode,
            rate_secret_file=secret,
        )

    def load_registry(self) -> Registry:
        try:
            document = json.loads(self.registry_file.read_text(encoding="utf-8"))
            return Registry.model_validate(document)
        except (OSError, ValueError) as exc:
            raise SettingsError("Approved upstream registry is unavailable or invalid") from exc

    def load_rate_secret(self) -> bytes:
        try:
            secret = self.rate_secret_file.read_bytes()
        except OSError as exc:
            raise SettingsError("Rate secret is unavailable") from exc
        if len(secret) < 32:
            raise SettingsError("Rate secret must contain at least 32 bytes")
        return secret
