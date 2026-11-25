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


def test_upload_is_ingested_by_the_worker_container(http):
    """Upload through the API container; the worker container indexes it."""
    import time
    import uuid

    alice = USERS["alice"]
    content = f"# Live check\n\nPolicy LIVE-{uuid.uuid4()} allows seven days.\n".encode()
    resp = http.post(
        f"/v1/organizations/{ACME_ID}/documents",
        files={"file": ("live.md", content)},
        headers=bearer(alice),
    )
    assert resp.status_code == 202, resp.text
    doc_id, job_id = resp.json()["document"]["id"], resp.json()["job"]["id"]

    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        job = http.get(f"/v1/organizations/{ACME_ID}/jobs/{job_id}", headers=bearer(alice)).json()
        if job["status"] in ("succeeded", "failed"):
            break
        time.sleep(1)
    assert job["status"] == "succeeded", job

    doc = http.get(f"/v1/organizations/{ACME_ID}/documents/{doc_id}", headers=bearer(alice)).json()
    assert doc["status"] == "ready" and doc["current_version"]["chunk_count"] >= 1
    version_id = doc["current_version"]["id"]
    link = http.get(
        f"/v1/organizations/{ACME_ID}/documents/{doc_id}/versions/{version_id}/download-url",
        headers=bearer(alice),
    ).json()["url"]
    assert httpx.get(link, timeout=5).content == content
    nova = http.get(
        f"/v1/organizations/{ACME_ID}/documents/{doc_id}", headers=bearer(USERS["nina"])
    )
    assert nova.status_code == 404


def test_chat_answers_with_citations_end_to_end(http):
    """Upload, wait for the worker, then ask through the running API."""
    import time
    import uuid

    alice = USERS["alice"]
    code = f"LIVE-{uuid.uuid4().hex[:8].upper()}"
    content = f"# Live chat\n\n## Window\n\nPolicy {code} allows refunds within 9 days.\n".encode()
    resp = http.post(
        f"/v1/organizations/{ACME_ID}/documents",
        files={"file": ("live-chat.md", content)},
        headers=bearer(alice),
    )
    job_id = resp.json()["job"]["id"]
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        job = http.get(f"/v1/organizations/{ACME_ID}/jobs/{job_id}", headers=bearer(alice)).json()
        if job["status"] in ("succeeded", "failed"):
            break
        time.sleep(1)
    assert job["status"] == "succeeded"
    answer = http.post(
        f"/v1/organizations/{ACME_ID}/chat",
        json={"question": f"What refund window does {code} allow?"},
        headers=bearer(alice),
        timeout=30,
    ).json()
    assert answer["status"] == "answered", answer
    assert "9 days" in answer["answer"]
    assert answer["citations"][0]["section"].endswith("Window")
