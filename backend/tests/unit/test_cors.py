from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import test_settings

ORIGIN = "https://atlas-ai.vercel.app"


def test_no_cors_by_default(client):
    resp = client.options(
        "/health", headers={"Origin": ORIGIN, "Access-Control-Request-Method": "GET"}
    )
    assert "access-control-allow-origin" not in resp.headers


def test_allowed_origin_only():
    app = create_app(test_settings("postgresql://x@127.0.0.1:1/x", cors_allowed_origins=ORIGIN))
    c = TestClient(app)
    ok = c.options(
        "/v1/organizations",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert ok.headers["access-control-allow-origin"] == ORIGIN
    evil = c.options(
        "/v1/organizations",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in evil.headers
