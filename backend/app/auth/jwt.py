"""Supabase JWT verification: signature, issuer, audience, expiry, subject."""

import logging
from dataclasses import dataclass
from uuid import UUID

import jwt

from app.config import Settings

logger = logging.getLogger(__name__)

ASYMMETRIC_ALGORITHMS = ["ES256", "RS256"]
REQUIRED_CLAIMS = ["exp", "iat", "sub", "aud", "iss"]


class AuthError(Exception):
    """Token missing or invalid. The message is safe to log, never the token."""


@dataclass(frozen=True)
class AuthUser:
    user_id: UUID
    email: str | None


class JWTVerifier:
    def __init__(self, settings: Settings) -> None:
        self._issuer = settings.supabase_jwt_issuer
        self._audience = settings.supabase_jwt_audience
        self._secret = (
            settings.supabase_jwt_secret.get_secret_value()
            if settings.supabase_jwt_secret
            else None
        )
        self._jwks = (
            jwt.PyJWKClient(settings.supabase_jwks_url) if settings.supabase_jwks_url else None
        )
        if self._jwks is None and not self._secret:
            logger.error(
                "no SUPABASE_JWKS_URL or SUPABASE_JWT_SECRET configured; rejecting all tokens"
            )

    def _key_and_algorithms(self, token: str):
        # Pick the algorithm list from server config, never from the token
        # header, so an HS256 token cannot be checked against a public key.
        if self._jwks is not None:
            return self._jwks.get_signing_key_from_jwt(token).key, ASYMMETRIC_ALGORITHMS
        if self._secret:
            return self._secret, ["HS256"]
        raise AuthError("authentication is not configured")

    def verify(self, token: str) -> AuthUser:
        try:
            key, algorithms = self._key_and_algorithms(token)
            claims = jwt.decode(
                token,
                key,
                algorithms=algorithms,
                audience=self._audience,
                issuer=self._issuer,
                options={"require": REQUIRED_CLAIMS},
            )
        except AuthError:
            raise
        except jwt.PyJWTError as exc:
            raise AuthError(f"invalid token: {type(exc).__name__}") from None

        if claims.get("role") != "authenticated":
            raise AuthError("token is not for an authenticated user")
        try:
            user_id = UUID(str(claims["sub"]))
        except ValueError:
            raise AuthError("invalid subject") from None
        email = claims.get("email")
        return AuthUser(user_id=user_id, email=email.lower() if isinstance(email, str) else None)
