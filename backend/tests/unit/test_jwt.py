"""Supabase JWT verification: issuer, audience, expiry, signature, subject."""

import uuid

import jwt
import pytest

from app.auth.jwt import AuthError, JWTVerifier
from app.config import Settings
from tests.helpers import JWT_AUDIENCE, JWT_ISSUER, JWT_SECRET, mint_token

USER = uuid.uuid4()


@pytest.fixture
def verifier() -> JWTVerifier:
    return JWTVerifier(
        Settings(
            supabase_jwt_secret=JWT_SECRET,
            supabase_jwt_issuer=JWT_ISSUER,
            supabase_jwt_audience=JWT_AUDIENCE,
        )
    )


def test_valid_token(verifier):
    user = verifier.verify(mint_token(USER, "a@example.com"))
    assert user.user_id == USER
    assert user.email == "a@example.com"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"expires_in": -60},
        {"issuer": "https://evil.example/auth/v1"},
        {"audience": "anon"},
        {"secret": "a-different-secret-that-is-also-32-characters"},
        {"role": "anon"},
        {"role": "service_role"},
    ],
    ids=["expired", "wrong-issuer", "wrong-audience", "bad-signature", "anon-role", "service-role"],
)
def test_rejected_tokens(verifier, kwargs):
    with pytest.raises(AuthError):
        verifier.verify(mint_token(USER, **kwargs))


def test_rejects_non_uuid_subject(verifier):
    with pytest.raises(AuthError):
        verifier.verify(mint_token("not-a-uuid"))


def test_rejects_missing_exp(verifier):
    token = jwt.encode(
        {"sub": str(USER), "aud": JWT_AUDIENCE, "iss": JWT_ISSUER, "role": "authenticated"},
        JWT_SECRET,
        algorithm="HS256",
    )
    with pytest.raises(AuthError):
        verifier.verify(token)


def test_rejects_alg_none(verifier):
    token = jwt.encode(
        {"sub": str(USER), "aud": JWT_AUDIENCE, "iss": JWT_ISSUER, "exp": 9999999999},
        key=None,
        algorithm="none",
    )
    with pytest.raises(AuthError):
        verifier.verify(token)


def test_rejects_garbage(verifier):
    with pytest.raises(AuthError):
        verifier.verify("not.a.jwt")


def test_fails_closed_without_key_config():
    verifier = JWTVerifier(Settings(supabase_jwt_secret=None, supabase_jwks_url=None))
    with pytest.raises(AuthError):
        verifier.verify(mint_token(USER))


def test_jwks_asymmetric_keys(monkeypatch):
    from cryptography.hazmat.primitives.asymmetric import ec

    private_key = ec.generate_private_key(ec.SECP256R1())
    verifier = JWTVerifier(
        Settings(
            supabase_jwks_url="https://project.supabase.co/auth/v1/.well-known/jwks.json",
            supabase_jwt_issuer=JWT_ISSUER,
            supabase_jwt_audience=JWT_AUDIENCE,
        )
    )

    class FakeKey:
        key = private_key.public_key()

    monkeypatch.setattr(verifier._jwks, "get_signing_key_from_jwt", lambda _t: FakeKey())
    token = mint_token(USER, secret=private_key, algorithm="ES256")
    assert verifier.verify(token).user_id == USER

    # Without a configured secret, HS256 tokens are rejected outright.
    with pytest.raises(AuthError):
        verifier.verify(mint_token(USER))


def test_jwks_and_legacy_secret_together(monkeypatch):
    """Projects migrating signing keys can accept both, each with its own key."""
    from cryptography.hazmat.primitives.asymmetric import ec

    private_key = ec.generate_private_key(ec.SECP256R1())
    verifier = JWTVerifier(
        Settings(
            supabase_jwks_url="https://project.supabase.co/auth/v1/.well-known/jwks.json",
            supabase_jwt_secret=JWT_SECRET,
            supabase_jwt_issuer=JWT_ISSUER,
            supabase_jwt_audience=JWT_AUDIENCE,
        )
    )

    class FakeKey:
        key = private_key.public_key()

    monkeypatch.setattr(verifier._jwks, "get_signing_key_from_jwt", lambda _t: FakeKey())
    assert verifier.verify(mint_token(USER, secret=private_key, algorithm="ES256")).user_id == USER
    assert verifier.verify(mint_token(USER)).user_id == USER  # HS256 with the secret
    with pytest.raises(AuthError):  # HS256 signed with anything else
        verifier.verify(mint_token(USER, secret="x" * 40))
