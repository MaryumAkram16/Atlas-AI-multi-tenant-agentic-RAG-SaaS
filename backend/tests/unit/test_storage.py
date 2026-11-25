import time
import uuid
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.documents.storage import LocalStorage, StorageError, SupabaseStorage, object_path

ORG, DOC, VER = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


@pytest.fixture
def store(tmp_path):
    return LocalStorage(tmp_path, signing_secret="s" * 32, public_base_url="http://api")


def test_object_path_is_tenant_scoped():
    assert object_path(ORG, DOC, VER, "../x/Policy.pdf") == f"{ORG}/{DOC}/{VER}/Policy.pdf"


def test_put_get_delete_prefix(store):
    path = object_path(ORG, DOC, VER, "a.txt")
    store.put(path, b"hello", "text/plain")
    assert store.get(path) == b"hello"
    store.delete_prefix(f"{ORG}/{DOC}/")
    with pytest.raises(StorageError):
        store.get(path)


@pytest.mark.parametrize("bad", ["../escape.txt", "/abs/path", f"{ORG}/../../x"])
def test_rejects_paths_outside_root(store, bad):
    with pytest.raises(StorageError):
        store.put(bad, b"x", "text/plain")


def test_signed_url_round_trip_and_expiry(store):
    path = object_path(ORG, DOC, VER, "a.txt")
    url = store.signed_url(path, ttl_seconds=60)
    q = parse_qs(urlparse(url).query)
    assert store.verify(path, int(q["expires"][0]), q["signature"][0])
    assert not store.verify(path, int(q["expires"][0]) + 1, q["signature"][0])
    other = object_path(uuid.uuid4(), DOC, VER, "a.txt")
    assert not store.verify(other, int(q["expires"][0]), q["signature"][0])
    assert not store.verify(path, int(time.time()) - 1, store._sign(path, int(time.time()) - 1))


def test_supabase_storage_uses_service_key_server_side():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if "/object/sign/" in request.url.path:
            return httpx.Response(200, json={"signedURL": "/object/sign/docs/p?token=t"})
        return httpx.Response(200, content=b"data")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    store = SupabaseStorage("https://proj.supabase.co", "service-key", "docs", client=client)
    store.put("o/d/v/a.txt", b"x", "text/plain")
    url = store.signed_url("o/d/v/a.txt", ttl_seconds=60)
    assert url == "https://proj.supabase.co/storage/v1/object/sign/docs/p?token=t"
    assert all(r.headers["authorization"] == "Bearer service-key" for r in seen)
    assert seen[1].read() == b'{"expiresIn":60}'


def test_supabase_delete_prefix_recurses_into_folders():
    deleted = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content or b"{}")
        if request.url.path.endswith("/object/list/docs"):
            if body["prefix"] == "o/d":
                return httpx.Response(200, json=[{"name": "v1", "id": None}])
            return httpx.Response(200, json=[{"name": "a.txt", "id": "1"}])
        if request.method == "DELETE":
            deleted.extend(body["prefixes"])
        return httpx.Response(200, json={})

    store = SupabaseStorage(
        "https://p.supabase.co",
        "k",
        "docs",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    store.delete_prefix("o/d/")
    assert deleted == ["o/d/v1/a.txt"]
