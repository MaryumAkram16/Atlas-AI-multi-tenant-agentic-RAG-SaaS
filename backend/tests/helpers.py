"""Shared test helpers: JWT minting and DB session helpers."""

import json
import time
from contextlib import contextmanager
from uuid import UUID

import jwt
import psycopg
from psycopg.rows import dict_row

JWT_SECRET = "test-only-jwt-secret-that-is-at-least-32-chars"
JWT_ISSUER = "http://localhost:54321/auth/v1"
JWT_AUDIENCE = "authenticated"


def mint_token(
    user_id: UUID | str,
    email: str | None = None,
    *,
    secret: str = JWT_SECRET,
    issuer: str = JWT_ISSUER,
    audience: str = JWT_AUDIENCE,
    expires_in: int = 300,
    algorithm: str = "HS256",
    **extra,
) -> str:
    now = int(time.time())
    claims = {
        "sub": str(user_id),
        "email": email,
        "role": "authenticated",
        "aud": audience,
        "iss": issuer,
        "iat": now,
        "exp": now + expires_in,
        **extra,
    }
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, secret, algorithm=algorithm)


def auth_header(user) -> dict[str, str]:
    """user is a SeedUser (has .id and .email)."""
    return {"Authorization": f"Bearer {mint_token(user.id, user.email)}"}


@contextmanager
def restricted_session(api_conninfo: str, user=None, *, anonymous: bool = False):
    """Direct DB access exactly like the API: log in as the restricted atlas_api
    role, then SET LOCAL ROLE authenticated with the user's claims.
    Yields a cursor inside a transaction that is rolled back afterwards."""
    with psycopg.connect(api_conninfo, row_factory=dict_row) as conn:
        with conn.transaction(force_rollback=True):
            conn.execute("SET LOCAL ROLE authenticated")
            if user is not None:
                claims = {"sub": str(user.id), "email": user.email, "role": "authenticated"}
                if anonymous:
                    claims["is_anonymous"] = True
                conn.execute(
                    "SELECT set_config('request.jwt.claims', %s, true)", (json.dumps(claims),)
                )
            yield conn
