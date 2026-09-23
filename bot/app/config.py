from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: str = Field(min_length=1)
    redis_url: str = "redis://redis:6379/0"
    mini_app_url: str = "https://example.invalid"
    temp_dir: Path = Path("/tmp/videocut")
    max_file_size_bytes: int = 20 * 1024 * 1024
    max_duration_seconds: float = 15 * 60
    session_ttl_seconds: int = 30 * 60

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("max_file_size_bytes")
    @classmethod
    def validate_file_size(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("max_file_size_bytes must be positive")
        return value

    @field_validator("max_duration_seconds")
    @classmethod
    def validate_duration(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("max_duration_seconds must be positive")
        return value

    @field_validator("session_ttl_seconds")
    @classmethod
    def validate_ttl(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("session_ttl_seconds must be positive")
        return value
