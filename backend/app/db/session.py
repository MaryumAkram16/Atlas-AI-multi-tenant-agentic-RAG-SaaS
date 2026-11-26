"""Per-request database sessions under the caller's identity.

Every transaction runs as `authenticated` with the verified JWT claims, so
Postgres RLS enforces tenant isolation even if a query forgets a filter.
"""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.auth.jwt import AuthUser
from app.config import Settings
from app.db.urls import libpq_url


def create_pool(settings: Settings) -> AsyncConnectionPool:
    return AsyncConnectionPool(
        libpq_url(settings.database_url.get_secret_value()),
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
        # prepare_threshold=None keeps us compatible with transaction poolers.
        kwargs={"row_factory": dict_row, "prepare_threshold": None},
        open=False,
    )


class UserDB:
    """Database access bound to one authenticated user."""

    def __init__(self, pool: AsyncConnectionPool, user: AuthUser) -> None:
        self._pool = pool
        self._claims = json.dumps(
            {
                "sub": str(user.user_id),
                "email": user.email,
                "role": "authenticated",
                "is_anonymous": user.is_anonymous,
            }
        )

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncConnection]:
        async with self._pool.connection() as conn, conn.transaction():
            # Both settings are transaction-local, so nothing leaks to the
            # next user of this pooled connection.
            await conn.execute("SET LOCAL ROLE authenticated")
            await conn.execute("SELECT set_config('request.jwt.claims', %s, true)", (self._claims,))
            yield conn
