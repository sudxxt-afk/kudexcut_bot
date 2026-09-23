from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "test-token")
    settings = Settings(_env_file=None)

    assert settings.redis_url == "redis://redis:6379/0"
    assert settings.mini_app_url == "http://localhost:8080"
    assert settings.temp_dir == Path("/tmp/videocut")
    assert settings.max_file_size_bytes == 500 * 1024 * 1024
    assert settings.max_duration_seconds == 900
    assert settings.session_ttl_seconds == 1800


def test_settings_load_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "BOT_TOKEN": "env-token",
        "REDIS_URL": "redis://localhost:6380/1",
        "MINI_APP_URL": "https://example.test",
        "TEMP_DIR": "/var/tmp/videocut",
        "MAX_FILE_SIZE_BYTES": "1024",
        "MAX_DURATION_SECONDS": "42.5",
        "SESSION_TTL_SECONDS": "60",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)

    settings = Settings(_env_file=None)

    assert settings.bot_token == "env-token"
    assert settings.redis_url == values["REDIS_URL"]
    assert settings.mini_app_url == values["MINI_APP_URL"]
    assert settings.temp_dir == Path(values["TEMP_DIR"])
    assert settings.max_file_size_bytes == 1024
    assert settings.max_duration_seconds == 42.5
    assert settings.session_ttl_seconds == 60


def test_settings_require_bot_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BOT_TOKEN", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_reject_non_positive_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "test-token")

    for field, value in (
        ("MAX_FILE_SIZE_BYTES", "0"),
        ("MAX_DURATION_SECONDS", "-1"),
        ("SESSION_TTL_SECONDS", "0"),
    ):
        monkeypatch.setenv(field, value)
        with pytest.raises(ValidationError):
            Settings(_env_file=None)
        monkeypatch.delenv(field)
