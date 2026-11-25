"""Object storage for original uploads.

Paths are always <org>/<document>/<version>/<file>. Files are only ever
served through short-lived signed URLs, issued after authorization.
"""

import hashlib
import hmac
import shutil
import time
from pathlib import Path
from typing import Protocol
from urllib.parse import quote, urlencode
from uuid import UUID

import httpx

from app.config import Settings
from app.documents.validation import safe_filename


class StorageError(Exception):
    pass


def object_path(org_id: UUID, document_id: UUID, version_id: UUID, filename: str) -> str:
    return f"{org_id}/{document_id}/{version_id}/{safe_filename(filename)}"


class ObjectStorage(Protocol):
    def put(self, path: str, data: bytes, content_type: str) -> None: ...
    def get(self, path: str) -> bytes: ...
    def delete_prefix(self, prefix: str) -> None: ...
    def signed_url(self, path: str, ttl_seconds: int) -> str: ...


class LocalStorage:
    """Filesystem storage for local dev and tests, with HMAC-signed URLs
    served by the API at /v1/files/{path}."""

    def __init__(self, root: Path | str, signing_secret: str, public_base_url: str) -> None:
        self.root = Path(root).resolve()
        self._secret = signing_secret.encode()
        self._base = public_base_url.rstrip("/")

    def _resolve(self, path: str) -> Path:
        if path.startswith("/") or "\\" in path:
            raise StorageError("invalid path")
        full = (self.root / path).resolve()
        if self.root not in full.parents:
            raise StorageError("path escapes storage root")
        return full

    def put(self, path: str, data: bytes, content_type: str) -> None:
        full = self._resolve(path)
        full.parent.mkdir(parents=True, exist_ok=True)
        tmp = full.with_suffix(full.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(full)

    def get(self, path: str) -> bytes:
        try:
            return self._resolve(path).read_bytes()
        except FileNotFoundError:
            raise StorageError("object not found") from None

    def delete_prefix(self, prefix: str) -> None:
        target = self._resolve(prefix.rstrip("/"))
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()

    def _sign(self, path: str, expires: int) -> str:
        return hmac.new(self._secret, f"{path}\n{expires}".encode(), hashlib.sha256).hexdigest()

    def signed_url(self, path: str, ttl_seconds: int) -> str:
        expires = int(time.time()) + ttl_seconds
        query = urlencode({"expires": expires, "signature": self._sign(path, expires)})
        return f"{self._base}/v1/files/{quote(path)}?{query}"

    def verify(self, path: str, expires: int, signature: str) -> bool:
        if expires < int(time.time()):
            return False
        return hmac.compare_digest(self._sign(path, expires), signature)


class SupabaseStorage:
    """Supabase Storage via its REST API. Uses the service role key server
    side only, after the API has authorized the request; the key never
    reaches clients or the database session."""

    def __init__(
        self, url: str, service_key: str, bucket: str, client: httpx.Client | None = None
    ) -> None:
        self._base = f"{url.rstrip('/')}/storage/v1"
        self._bucket = bucket
        self._client = client or httpx.Client(timeout=30)
        self._headers = {"Authorization": f"Bearer {service_key}", "apikey": service_key}

    def _check(self, resp: httpx.Response) -> httpx.Response:
        if resp.status_code >= 400:
            raise StorageError(f"storage error {resp.status_code}")
        return resp

    def put(self, path: str, data: bytes, content_type: str) -> None:
        self._check(
            self._client.post(
                f"{self._base}/object/{self._bucket}/{quote(path)}",
                content=data,
                headers={**self._headers, "Content-Type": content_type, "x-upsert": "true"},
            )
        )

    def get(self, path: str) -> bytes:
        return self._check(
            self._client.get(
                f"{self._base}/object/{self._bucket}/{quote(path)}", headers=self._headers
            )
        ).content

    def delete_prefix(self, prefix: str) -> None:
        listing = self._check(
            self._client.post(
                f"{self._base}/object/list/{self._bucket}",
                json={"prefix": prefix.rstrip("/"), "limit": 1000},
                headers=self._headers,
            )
        ).json()
        base = prefix.rstrip("/")
        # Supabase lists sub-folders as entries without an id.
        for item in listing:
            if item.get("id") is None:
                self.delete_prefix(f"{base}/{item['name']}/")
        files = [f"{base}/{item['name']}" for item in listing if item.get("id") is not None]
        if files:
            self._check(
                self._client.request(
                    "DELETE",
                    f"{self._base}/object/{self._bucket}",
                    json={"prefixes": files},
                    headers=self._headers,
                )
            )

    def signed_url(self, path: str, ttl_seconds: int) -> str:
        data = self._check(
            self._client.post(
                f"{self._base}/object/sign/{self._bucket}/{quote(path)}",
                json={"expiresIn": ttl_seconds},
                headers=self._headers,
            )
        ).json()
        return f"{self._base}{data['signedURL']}"


def build_storage(settings: Settings) -> LocalStorage | SupabaseStorage:
    if settings.storage_backend == "supabase":
        if not settings.supabase_url or settings.supabase_service_role_key is None:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
        return SupabaseStorage(
            settings.supabase_url,
            settings.supabase_service_role_key.get_secret_value(),
            settings.supabase_storage_bucket,
        )
    return LocalStorage(
        settings.local_storage_path,
        settings.storage_signing_secret.get_secret_value(),
        settings.public_base_url,
    )
