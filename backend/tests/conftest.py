import os

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

from app.config import Settings
from app.main import create_app
from tests.helpers import JWT_AUDIENCE, JWT_ISSUER, JWT_SECRET

ADMIN_URL = os.environ.get(
    "TEST_ADMIN_DATABASE_URL", "postgresql://postgres:postgres@localhost:54322/postgres"
)
API_DB_PASSWORD = os.environ.get("ATLAS_API_DB_PASSWORD", "atlas_api_local_password")
TEST_DB = "atlas_test"


def _url(base: str, **parts) -> str:
    return make_url(base).set(**parts).render_as_string(hide_password=False)


def _require_or_skip(reason: str):
    if os.environ.get("ATLAS_REQUIRE_STACK"):
        pytest.fail(reason)
    pytest.skip(reason)


@pytest.fixture
def client() -> TestClient:
    """App without a database: fine for endpoints that never touch Postgres."""
    return TestClient(create_app(test_settings("postgresql://nobody@127.0.0.1:1/none")))


def test_settings(database_url: str) -> Settings:
    return Settings(
        app_env="test",
        database_url=database_url,
        qdrant_url="http://127.0.0.1:1",
        supabase_jwt_secret=JWT_SECRET,
        supabase_jwt_issuer=JWT_ISSUER,
        supabase_jwt_audience=JWT_AUDIENCE,
    )


test_settings.__test__ = False  # not a test, despite the name


@pytest.fixture(scope="session")
def admin_url() -> str:
    try:
        psycopg.connect(ADMIN_URL, connect_timeout=2).close()
    except psycopg.OperationalError:
        _require_or_skip("Postgres not reachable; run `docker compose up -d db`")
    return ADMIN_URL


@pytest.fixture(scope="session")
def test_db(admin_url):
    """A fresh database migrated from scratch, plus URLs for admin and API roles."""
    from app.db import migrate

    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{TEST_DB}"')
    db_admin_url = _url(admin_url, database=TEST_DB)
    migrate.upgrade(db_admin_url)
    migrate.set_api_role_password(db_admin_url, API_DB_PASSWORD)
    yield {
        "admin": db_admin_url,
        "api": _url(admin_url, database=TEST_DB, username="atlas_api", password=API_DB_PASSWORD),
    }
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')


@pytest.fixture
def seeded(test_db):
    """Reset tenant data to the Acme/Nova seed before each test."""
    from app.tenants import seed

    with psycopg.connect(test_db["admin"]) as conn:
        conn.execute("TRUNCATE public.organizations CASCADE")
        seed.seed(conn)
    return test_db


@pytest.fixture
def api(seeded):
    with TestClient(create_app(test_settings(seeded["api"]))) as c:
        yield c
