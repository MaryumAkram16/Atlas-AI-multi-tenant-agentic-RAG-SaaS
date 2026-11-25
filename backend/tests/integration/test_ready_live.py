"""Runs against the docker compose stack: `pytest -m integration`."""

import os

import httpx
import pytest

pytestmark = pytest.mark.integration

API_URL = os.environ.get("ATLAS_API_URL", "http://localhost:8000")


def test_ready_against_running_stack():
    try:
        resp = httpx.get(f"{API_URL}/ready", timeout=5)
    except httpx.ConnectError:
        if os.environ.get("ATLAS_REQUIRE_STACK"):
            raise
        pytest.skip(f"API not running at {API_URL}")
    assert resp.status_code == 200
    assert resp.json()["checks"] == {"postgres": True, "qdrant": True}
