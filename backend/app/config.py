"""Application settings, loaded from environment variables (see .env.example)."""

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "atlas-ai"
    app_env: str = "local"
    log_level: str = "INFO"

    # SecretStr keeps the password out of reprs and logs.
    database_url: SecretStr = SecretStr("postgresql://postgres:postgres@localhost:5432/postgres")
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: SecretStr | None = None

    ready_check_timeout_seconds: float = Field(default=2.0, gt=0)
    worker_poll_interval_seconds: float = Field(default=5.0, gt=0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
