"""Dependency checks for the /ready endpoint."""

import asyncio
import logging

import httpx
import psycopg

from app.config import Settings

logger = logging.getLogger(__name__)


async def check_postgres(settings: Settings) -> bool:
    try:
        async with await psycopg.AsyncConnection.connect(
            settings.database_url.get_secret_value(),
            connect_timeout=max(1, int(settings.ready_check_timeout_seconds)),
        ) as conn:
            await conn.execute("SELECT 1")
        return True
    except Exception as exc:
        # Log only the exception type: messages can contain connection details.
        logger.warning("postgres readiness check failed: %s", type(exc).__name__)
        return False


async def check_qdrant(settings: Settings) -> bool:
    headers = {}
    if settings.qdrant_api_key is not None:
        headers["api-key"] = settings.qdrant_api_key.get_secret_value()
    try:
        async with httpx.AsyncClient(timeout=settings.ready_check_timeout_seconds) as client:
            resp = await client.get(f"{settings.qdrant_url.rstrip('/')}/readyz", headers=headers)
        return resp.status_code == 200
    except Exception as exc:
        logger.warning("qdrant readiness check failed: %s", type(exc).__name__)
        return False


async def run_checks(settings: Settings) -> dict[str, bool]:
    postgres, qdrant = await asyncio.gather(check_postgres(settings), check_qdrant(settings))
    return {"postgres": postgres, "qdrant": qdrant}
