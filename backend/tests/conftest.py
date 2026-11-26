import os

import httpx
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
QDRANT_URL = os.environ.get("TEST_QDRANT_URL", "http://localhost:6333")
API_DB_PASSWORD = os.environ.get("ATLAS_API_DB_PASSWORD", "atlas_api_local_password")
WORKER_DB_PASSWORD = os.environ.get("ATLAS_WORKER_DB_PASSWORD", "atlas_worker_local_password")
TEST_DB = "atlas_test"
TEST_COLLECTION = "atlas_chunks_test"
TEST_DIMENSIONS = 64


def _url(base: str, **parts) -> str:
    return make_url(base).set(**parts).render_as_string(hide_password=False)


def _require_or_skip(reason: str):
    if os.environ.get("ATLAS_REQUIRE_STACK"):
        pytest.fail(reason)
    pytest.skip(reason)


def test_settings(database_url: str, **overrides) -> Settings:
    values = {
        "app_env": "test",
        "database_url": database_url,
        "qdrant_url": "http://127.0.0.1:1",
        "supabase_jwt_secret": JWT_SECRET,
        "supabase_jwt_issuer": JWT_ISSUER,
        "supabase_jwt_audience": JWT_AUDIENCE,
        "storage_backend": "local",
        "storage_signing_secret": "test-storage-signing-secret-32-chars!",
        "qdrant_collection": TEST_COLLECTION,
        "embedding_provider": "hash",
        "embedding_dimensions": TEST_DIMENSIONS,
        "tokenizer": "simple",
        "llm_provider": "extractive",
        "job_backoff_base_seconds": 0,
        "max_upload_bytes": 1024 * 1024,
        # Limits are exercised by dedicated tests; keep them out of the way elsewhere.
        "rate_limit_chat": 10_000,
        "rate_limit_upload": 10_000,
    }
    values.update(overrides)
    return Settings(**values)


test_settings.__test__ = False  # not a test, despite the name


@pytest.fixture
def client() -> TestClient:
    """App without a database: fine for endpoints that never touch Postgres."""
    return TestClient(create_app(test_settings("postgresql://nobody@127.0.0.1:1/none")))


@pytest.fixture(scope="session")
def admin_url() -> str:
    try:
        psycopg.connect(ADMIN_URL, connect_timeout=2).close()
    except psycopg.OperationalError:
        _require_or_skip("Postgres not reachable; run `docker compose up -d db`")
    return ADMIN_URL


@pytest.fixture(scope="session")
def qdrant_url() -> str:
    try:
        httpx.get(f"{QDRANT_URL}/readyz", timeout=2).raise_for_status()
    except httpx.HTTPError:
        _require_or_skip("Qdrant not reachable; run `docker compose up -d qdrant`")
    return QDRANT_URL


@pytest.fixture(scope="session")
def test_db(admin_url):
    """A fresh database migrated from scratch, plus URLs for each role."""
    from app.db import migrate

    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{TEST_DB}"')
    db_admin_url = _url(admin_url, database=TEST_DB)
    migrate.upgrade(db_admin_url)
    migrate.set_role_password(db_admin_url, "atlas_api", API_DB_PASSWORD)
    migrate.set_role_password(db_admin_url, "atlas_worker", WORKER_DB_PASSWORD)
    yield {
        "admin": db_admin_url,
        "api": _url(admin_url, database=TEST_DB, username="atlas_api", password=API_DB_PASSWORD),
        "worker": _url(
            admin_url, database=TEST_DB, username="atlas_worker", password=WORKER_DB_PASSWORD
        ),
    }
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')


@pytest.fixture
def seeded(test_db):
    """Reset tenant data to the Acme/Nova seed before each test."""
    from app.tenants import seed

    with psycopg.connect(test_db["admin"]) as conn:
        conn.execute("TRUNCATE public.organizations CASCADE")
        conn.execute(
            "TRUNCATE public.audit_logs, app_private.rate_limit_counters, app_private.demo_config"
        )
        seed.seed(conn)
    return test_db


@pytest.fixture
def api(seeded):
    with TestClient(create_app(test_settings(seeded["api"]))) as c:
        yield c


# ---------- ingestion (Postgres + Qdrant + local storage) ----------


@pytest.fixture
def ingestion_settings(seeded, qdrant_url, tmp_path) -> Settings:
    return test_settings(
        seeded["api"],
        worker_database_url=seeded["worker"],
        qdrant_url=qdrant_url,
        local_storage_path=str(tmp_path / "storage"),
    )


@pytest.fixture
def vector_index(ingestion_settings):
    from app.retrieval.index import VectorIndex

    index = VectorIndex.from_settings(ingestion_settings)
    index.drop_collection()
    index.ensure_collection()
    yield index
    index.drop_collection()


@pytest.fixture
def docs_api(ingestion_settings, vector_index):
    with TestClient(create_app(ingestion_settings)) as c:
        yield c


@pytest.fixture
def worker(ingestion_settings, vector_index):
    from app.workers.ingestion import IngestionWorker

    w = IngestionWorker.from_settings(ingestion_settings, worker_id="test-worker")
    yield w
    w.close()
