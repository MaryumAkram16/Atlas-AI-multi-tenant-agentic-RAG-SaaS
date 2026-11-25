"""Every route, enumerated from the app itself: cross-tenant calls never
succeed and unauthenticated calls are rejected. New endpoints are covered
automatically."""

import uuid

import pytest

from app.tenants.seed import ACME_ID, NOVA_ID, USERS
from tests.helpers import auth_header

pytestmark = pytest.mark.db

PUBLIC = {"/health", "/ready", "/v1/files/{path:path}"}


def api_routes(app):
    """Every documented path and method (the OpenAPI schema is the inventory)."""
    for path, ops in app.openapi()["paths"].items():
        if path in PUBLIC or path.startswith("/v1/files") or not path.startswith("/v1"):
            continue
        for method in ops:
            yield method.upper(), path


def fill(path: str, org_id) -> str:
    out = path.replace("{org_id}", str(org_id))
    for name in ("document_id", "version_id", "member_id", "job_id", "chunk_id", "conversation_id"):
        out = out.replace("{" + name + "}", str(uuid.uuid4()))
    return out


def call(api, method, url, headers):
    kwargs = {"headers": headers}
    if method in ("POST", "PATCH"):
        kwargs["json"] = {}
    return api.request(method, url, **kwargs)


def test_route_inventory_is_not_empty(api):
    routes = list(api_routes(api.app))
    assert len([r for r in routes if "{org_id}" in r[1]]) >= 15


def test_every_org_route_rejects_other_tenants(api):
    """Nova's owner against Acme's organization ID: always 403/404, never data."""
    checked = 0
    for method, path in api_routes(api.app):
        if "{org_id}" not in path:
            continue
        resp = call(api, method, fill(path, ACME_ID), auth_header(USERS["nina"]))
        assert resp.status_code in (403, 404), f"{method} {path} -> {resp.status_code}"
        assert "error" in resp.json()
        checked += 1
    assert checked >= 15


def test_every_api_route_requires_authentication(api):
    for method, path in api_routes(api.app):
        resp = call(api, method, fill(path, NOVA_ID), {})
        assert resp.status_code == 401, f"{method} {path} -> {resp.status_code}"
        assert resp.json()["error"]["code"] == "unauthenticated"
