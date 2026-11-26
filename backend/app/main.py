"""FastAPI application factory: `uvicorn app.main:create_app --factory`.

Providers (embeddings, LLM, storage) are built at startup, so a missing key
fails fast instead of on the first request."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin import router as admin_router
from app.api.chat import router as chat_router
from app.api.documents import files_router
from app.api.documents import router as documents_router
from app.api.errors import install_error_handlers
from app.api.evaluations import router as evaluations_router
from app.api.feedback import router as feedback_router
from app.api.health import router as health_router
from app.api.organizations import router as organizations_router
from app.auth.jwt import JWTVerifier
from app.config import Settings, get_settings
from app.db.session import create_pool
from app.documents.storage import build_storage
from app.middleware.request_context import RequestContextMiddleware
from app.observability.logging import configure_logging
from app.observability.tracing import setup_tracing
from app.retrieval.embeddings import build_embedder
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.index import VectorIndex
from app.services.llm import build_llm

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_logs=settings.log_format == "json")
    setup_tracing("atlas-api", settings.otel_exporter_otlp_endpoint)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        pool = create_pool(settings)
        # Don't block startup on the database; /ready reports its state.
        await pool.open(wait=False)
        app.state.db_pool = pool
        try:
            yield
        finally:
            await pool.close()

    app = FastAPI(title="Atlas AI API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.jwt_verifier = JWTVerifier(settings)
    app.state.storage = build_storage(settings)
    app.state.retriever = HybridRetriever(
        VectorIndex.from_settings(settings),
        build_embedder(settings),
        dense_k=settings.retrieval_dense_k,
        sparse_k=settings.retrieval_sparse_k,
        fused_k=settings.retrieval_fused_k,
        rrf_k=settings.rrf_k,
    )
    app.state.llm = build_llm(settings)
    # Health checks read settings via dependency; keep them consistent.
    app.dependency_overrides[get_settings] = lambda: settings

    install_error_handlers(app)

    origins = [o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()]
    if origins:
        # Exact origins only (no wildcard): bearer tokens, no cookies.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "Accept"],
            allow_credentials=False,
            max_age=600,
        )

    # Outermost: every request (and error) gets a request ID and a server span.
    app.add_middleware(RequestContextMiddleware)

    app.include_router(health_router)
    app.include_router(organizations_router)
    app.include_router(documents_router)
    app.include_router(chat_router)
    app.include_router(admin_router)
    app.include_router(evaluations_router)
    app.include_router(feedback_router)
    app.include_router(files_router)
    return app
