from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: str = Field(min_length=1)
    redis_url: str = "redis://redis:6379/0"
    temp_dir: Path = Path("/tmp/videocut")
    telegram_init_data_max_age_seconds: int = 86400

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
