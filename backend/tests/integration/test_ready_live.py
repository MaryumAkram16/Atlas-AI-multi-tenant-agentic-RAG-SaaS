"""Runs against the docker compose stack (`pytest -m integration`).

Expects the stack to be seeded: docker compose run --rm migrate python -m app.db.manage seed
"""

import os

import httpx
import pytest

from app.tenants.seed import ACME_ID, NOVA_ID, USERS
from tests.helpers import mint_token

pytestmark = pytest.mark.integration

API_URL = os.environ.get("ATLAS_API_URL", "http://localhost:8000")
# Matches the local-only value in .env.example.
JWT_SECRET = os.environ.get(
    "SUPABASE_JWT_SECRET", "local-dev-only-jwt-secret-at-least-32-characters"
)


@pytest.fixture(scope="module")
def http():
    client = httpx.Client(base_url=API_URL, timeout=5)
    try:
        client.get("/health")
    except httpx.ConnectError:
        if os.environ.get("ATLAS_REQUIRE_STACK"):
            raise
        pytest.skip(f"API not running at {API_URL}")
    yield client
    client.close()


def bearer(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {mint_token(user.id, user.email, secret=JWT_SECRET)}"}


def test_ready_against_running_stack(http):
    resp = http.get("/ready")
    assert resp.status_code == 200
    assert resp.json()["checks"] == {"postgres": True, "qdrant": True}


def test_auth_required(http):
    assert http.get("/v1/organizations").status_code == 401


def test_tenant_isolation_end_to_end(http):
    acme = http.get("/v1/organizations", headers=bearer(USERS["alice"]))
    assert acme.status_code == 200
    assert [o["id"] for o in acme.json()] == [str(ACME_ID)]
    nova = http.get("/v1/organizations", headers=bearer(USERS["nina"]))
    assert [o["id"] for o in nova.json()] == [str(NOVA_ID)]
    resp = http.get(f"/v1/organizations/{ACME_ID}/members", headers=bearer(USERS["nina"]))
    assert resp.status_code == 404
