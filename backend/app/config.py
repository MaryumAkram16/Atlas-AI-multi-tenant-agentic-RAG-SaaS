"""Application settings, loaded from environment variables (see .env.example)."""

from functools import lru_cache
from typing import Literal

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
    # Ingestion worker login (atlas_worker): pinned per job to one tenant by RLS.
    worker_database_url: SecretStr = SecretStr(
        "postgresql://atlas_worker:atlas_worker_local_password@localhost:54322/postgres"
    )
    atlas_worker_db_password: SecretStr | None = None
    db_pool_min_size: int = Field(default=1, ge=0)
    db_pool_max_size: int = Field(default=10, ge=1)

    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: SecretStr | None = None
    qdrant_collection: str = "atlas_chunks"

    # Uploads and object storage. The API authorizes first, then serves files
    # only through short-lived signed URLs.
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, ge=1)
    storage_backend: Literal["local", "supabase"] = "local"
    local_storage_path: str = "./.storage"
    storage_signing_secret: SecretStr = SecretStr("local-dev-only-storage-signing-secret")
    public_base_url: str = "http://localhost:8000"
    signed_url_ttl_seconds: int = Field(default=120, ge=10, le=300)
    supabase_url: str | None = None
    supabase_service_role_key: SecretStr | None = None
    supabase_storage_bucket: str = "documents"

    # Chunking and embeddings
    tokenizer: Literal["tiktoken", "simple"] = "tiktoken"
    chunk_tokens: int = Field(default=512, ge=32)
    chunk_overlap_tokens: int = Field(default=64, ge=0)
    embedding_provider: Literal["openai", "hash"] = "openai"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = Field(default=1536, ge=8)
    openai_api_key: SecretStr | None = None
    openai_base_url: str = "https://api.openai.com/v1"

    # Job queue
    job_max_attempts: int = Field(default=5, ge=1, le=20)
    job_backoff_base_seconds: float = Field(default=5.0, ge=0)
    job_backoff_max_seconds: float = Field(default=300.0, ge=0)
    job_lease_seconds: int = Field(default=600, ge=30)

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
