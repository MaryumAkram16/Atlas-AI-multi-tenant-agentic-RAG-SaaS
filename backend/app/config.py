"""Application settings, loaded from environment variables (see .env.example)."""

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "atlas-ai"
    app_env: str = "local"
    log_level: str = "INFO"

    # Restricted login role used for every request (atlas_api). Never the
    # service role or the migration owner. SecretStr keeps passwords out of logs.
    database_url: SecretStr = SecretStr(
        "postgresql://atlas_api:atlas_api_local_password@localhost:54322/postgres"
    )
    # Schema owner used only by migrations and the seed script.
    migration_database_url: SecretStr = SecretStr(
        "postgresql://postgres:postgres@localhost:54322/postgres"
    )
    atlas_api_db_password: SecretStr | None = None
    db_pool_min_size: int = Field(default=1, ge=0)
    db_pool_max_size: int = Field(default=10, ge=1)

    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: SecretStr | None = None

    # Supabase Auth. Use the JWKS URL (asymmetric keys) when set, otherwise the
    # legacy HS256 secret. With neither, every token is rejected.
    supabase_jwks_url: str | None = None
    supabase_jwt_secret: SecretStr | None = None
    supabase_jwt_issuer: str = "http://localhost:54321/auth/v1"
    supabase_jwt_audience: str = "authenticated"

    invitation_ttl_hours: int = Field(default=72, ge=1, le=24 * 30)

    ready_check_timeout_seconds: float = Field(default=2.0, gt=0)
    worker_poll_interval_seconds: float = Field(default=5.0, gt=0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
