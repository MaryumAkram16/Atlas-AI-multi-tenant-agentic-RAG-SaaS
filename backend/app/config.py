"""Application settings, loaded from environment variables (see .env.example)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Empty variables in .env (e.g. `QDRANT_API_KEY=`) mean "not set".
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    app_name: str = "atlas-ai"
    # Browser origins allowed to call the API cross-origin (comma-separated),
    # e.g. the Vercel frontend. Empty: same-origin only (compose / Vite proxy).
    cors_allowed_origins: str = ""
    app_env: str = "local"
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"
    # OpenTelemetry collector (OTLP/HTTP), e.g. http://otel-collector:4318. Unset: no export.
    otel_exporter_otlp_endpoint: str | None = None

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

    # Retrieval and answering
    retrieval_dense_k: int = Field(default=20, ge=1, le=100)
    retrieval_sparse_k: int = Field(default=20, ge=1, le=100)
    retrieval_fused_k: int = Field(default=20, ge=1, le=100)
    rrf_k: int = Field(default=60, ge=1)
    answer_max_chunks: int = Field(default=8, ge=1, le=20)
    chat_history_messages: int = Field(default=6, ge=0, le=20)
    llm_provider: Literal["openai", "extractive"] = "openai"
    llm_model: str = "gpt-4o-mini"
    llm_max_tokens: int = Field(default=800, ge=16)
    # For thinking models only (e.g. "low" for Gemini); unset for gpt-4o-mini.
    llm_reasoning_effort: str | None = None
    llm_timeout_seconds: float = Field(default=60, gt=0)
    # Optional prices (USD per 1M tokens) for usage cost estimates; unset = no estimate.
    llm_input_price_per_1m: float | None = Field(default=None, ge=0)
    llm_output_price_per_1m: float | None = Field(default=None, ge=0)

    # Agent limits
    agent_max_steps: int = Field(default=24, ge=6, le=100)
    agent_max_rewrites: int = Field(default=2, ge=0, le=5)
    agent_max_corrections: int = Field(default=1, ge=0, le=3)
    agent_timeout_seconds: float = Field(default=45, gt=0)
    agent_max_evidence_tokens: int = Field(default=6000, ge=500)
    agent_sufficient_coverage: float = Field(default=0.6, gt=0, le=1)
    # Stage switches, used by the ablation benchmark (all on in production).
    agent_enable_rewrite: bool = True
    agent_enable_conflicts: bool = True
    agent_enable_verification: bool = True
    agent_enable_injection_filter: bool = True

    # Rate limits (per user, per organization, fixed window)
    rate_limit_window_seconds: int = Field(default=60, ge=1)
    rate_limit_chat: int = Field(default=20, ge=1)
    rate_limit_upload: int = Field(default=30, ge=1)
    rate_limit_evaluation: int = Field(default=3, ge=1)

    # In-product evaluations run synchronously, so runs are capped.
    evaluation_max_cases: int = Field(default=50, ge=1, le=500)

    # Per-tenant quotas by plan (enterprise is unlimited)
    quota_free_documents: int = Field(default=100, ge=0)
    quota_free_storage_mb: int = Field(default=200, ge=0)
    quota_free_questions_per_day: int = Field(default=300, ge=0)
    quota_pro_documents: int = Field(default=5000, ge=0)
    quota_pro_storage_mb: int = Field(default=20_000, ge=0)
    quota_pro_questions_per_day: int = Field(default=10_000, ge=0)

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
