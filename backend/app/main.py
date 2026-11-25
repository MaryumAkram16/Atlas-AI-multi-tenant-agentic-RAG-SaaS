"""FastAPI application entry point."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from psycopg import errors

from app.api.documents import files_router
from app.api.documents import router as documents_router
from app.api.health import router as health_router
from app.api.organizations import router as organizations_router
from app.auth.jwt import JWTVerifier
from app.config import Settings, get_settings
from app.db.session import create_pool
from app.documents.storage import build_storage
from app.observability.logging import configure_logging

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

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
    # Health checks read settings via dependency; keep them consistent.
    app.dependency_overrides[get_settings] = lambda: settings

    @app.exception_handler(errors.InsufficientPrivilege)
    async def rls_denied(_request: Request, _exc: errors.InsufficientPrivilege) -> JSONResponse:
        # Postgres refused (RLS or grants). Don't echo database messages.
        return JSONResponse({"detail": "not allowed"}, status_code=status.HTTP_403_FORBIDDEN)

    app.include_router(health_router)
    app.include_router(organizations_router)
    app.include_router(documents_router)
    app.include_router(files_router)
    return app


app = create_app()
