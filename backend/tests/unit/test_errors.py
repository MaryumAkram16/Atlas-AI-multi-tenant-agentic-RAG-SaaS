"""One error format everywhere, with request IDs and no leaked internals."""

from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import test_settings
from tests.helpers import mint_token


def app_with_boom():
    app = create_app(test_settings("postgresql://x@127.0.0.1:1/x"))
    router = APIRouter()

    @router.get("/boom")
    async def boom():
        raise RuntimeError("secret internal detail: password=hunter2")

    app.include_router(router)
    return app


def test_not_found_and_unauthenticated_shape(client):
    resp = client.get("/v1/organizations")
    assert resp.status_code == 401
    err = resp.json()["error"]
    assert err["code"] == "unauthenticated" and err["message"]
    assert err["request_id"] == resp.headers["x-request-id"]
    assert client.get("/nope").json()["error"]["code"] == "not_found"


def test_validation_errors_do_not_echo_input():
    secret = "my-secret-value-xyz"
    token = mint_token("1a000000-0000-4000-8000-000000000001")
    with TestClient(create_app(test_settings("postgresql://x@127.0.0.1:1/x"))) as client:
        resp = client.post(
            "/v1/organizations",
            json={"name": "", "slug": secret + "!!"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 422
    err = resp.json()["error"]
    assert err["code"] == "validation_error" and err["details"]
    assert secret not in resp.text


def test_unexpected_errors_are_opaque():
    client = TestClient(app_with_boom(), raise_server_exceptions=False)
    resp = client.get("/boom")
    assert resp.status_code == 500
    assert resp.json()["error"]["code"] == "internal_error"
    assert "hunter2" not in resp.text and "secret" not in resp.text


def test_request_id_is_propagated_or_generated(client):
    given = client.get("/health", headers={"X-Request-ID": "trace-abc-12345"})
    assert given.headers["x-request-id"] == "trace-abc-12345"
    unsafe = client.get("/health", headers={"X-Request-ID": "<script>"})
    assert (
        unsafe.headers["x-request-id"] != "<script>" and len(unsafe.headers["x-request-id"]) == 32
    )
