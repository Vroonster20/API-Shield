import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_configured_default_password_is_rejected(monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "changeme")

    with pytest.raises(
        ValidationError,
        match="ADMIN_PASSWORD must not be changeme",
    ):
        Settings(_env_file=None)


def test_missing_password_rejects_fallback_default(monkeypatch):
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)

    with pytest.raises(
        ValidationError,
        match="ADMIN_PASSWORD must not be changeme",
    ):
        Settings(_env_file=None)