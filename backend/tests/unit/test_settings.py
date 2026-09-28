import json

import pytest

from shield_api.settings import Settings, SettingsError


def test_explicit_environment_is_injectable_and_registry_is_strict(tmp_path):
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "upstreams": [
                    {"id": "demo-origin", "name": "Demo", "scheme": "http", "host": "127.0.0.1", "port": 9000}
                ]
            }
        ),
        encoding="utf-8",
    )
    settings = Settings.from_env(
        {
            "SHIELD_DATA_DIR": str(tmp_path / "runtime"),
            "SHIELD_REGISTRY_FILE": str(registry),
            "SHIELD_ADMIN_ORIGIN": "http://admin.localhost:8081",
            "SHIELD_MODE": "development",
        }
    )
    assert settings.db_path.parent == (tmp_path / "runtime").resolve()
    assert settings.load_registry().upstreams[0].id == "demo-origin"
    assert settings.rate_secret_file == (tmp_path / "runtime" / "rate.key").resolve()
    assert not settings.rate_secret_file.exists()


@pytest.mark.parametrize(
    "origin",
    [
        "http://admin.localhost:8081/path",
        "http://user@admin.localhost:8081",
        "http://admin.localhost:bad",
        "http://example.com:8081",
    ],
)
def test_invalid_admin_origins_rejected(tmp_path, origin):
    with pytest.raises(SettingsError):
        Settings(
            data_dir=tmp_path,
            registry_file=tmp_path / "registry.json",
            admin_origin=origin,
            mode="development",
            rate_secret_file=tmp_path / "rate.key",
        )


def test_production_requires_https(tmp_path):
    with pytest.raises(SettingsError):
        Settings(
            data_dir=tmp_path,
            registry_file=tmp_path / "registry.json",
            admin_origin="http://admin.example:8081",
            mode="production",
            rate_secret_file=tmp_path / "rate.key",
        )
