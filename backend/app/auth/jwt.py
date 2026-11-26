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
    # Supabase anonymous sign-in (demo visitors); no email, limited rights.
    is_anonymous: bool = False


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
        # Each key type is paired with its own algorithms, never chosen by the
        # token alone: an HS256 token is only ever checked against the shared
        # secret (if one is configured), never against a JWKS public key.
        try:
            alg = jwt.get_unverified_header(token).get("alg")
        except jwt.PyJWTError:
            raise AuthError("invalid token header") from None
        if alg == "HS256":
            if self._secret:
                return self._secret, ["HS256"]
            raise AuthError("HS256 tokens are not accepted")
        if self._jwks is not None:
            return self._jwks.get_signing_key_from_jwt(token).key, ASYMMETRIC_ALGORITHMS
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
        except (jwt.PyJWTError, jwt.PyJWKClientError) as exc:
            raise AuthError(f"invalid token: {type(exc).__name__}") from None

        if claims.get("role") != "authenticated":
            raise AuthError("token is not for an authenticated user")
        try:
            user_id = UUID(str(claims["sub"]))
        except ValueError:
            raise AuthError("invalid subject") from None
        email = claims.get("email")
        return AuthUser(
            user_id=user_id,
            email=email.lower() if isinstance(email, str) else None,
            is_anonymous=claims.get("is_anonymous") is True,
        )
