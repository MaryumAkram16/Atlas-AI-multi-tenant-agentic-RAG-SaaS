"""Dense embedding providers behind one small interface (replaceable)."""

import hashlib
import math
import time
from typing import Protocol

import httpx

from app.config import Settings
from app.retrieval.sparse import tokenize
from app.services.retry import RETRYABLE_STATUS, backoff


class Embedder(Protocol):
    dimensions: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashEmbedder:
    """Deterministic, offline embeddings (feature hashing of terms). For local
    development and tests only: no semantic understanding."""

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            vec = [0.0] * self.dimensions
            for term in tokenize(text):
                h = hashlib.blake2b(term.encode(), digest_size=8).digest()
                vec[int.from_bytes(h[:4], "big") % self.dimensions] += 1.0 if h[4] & 1 else -1.0
            norm = math.sqrt(sum(x * x for x in vec)) or 1.0
            out.append([x / norm for x in vec])
        return out


def _ordered_embeddings(data: list[dict], expected: int) -> list[list[float]]:
    """Embeddings in input order. Some OpenAI-compatible APIs (Gemini) omit
    `"index": 0`, as zero is the default value, so a missing index means 0;
    duplicates fall back to response order."""
    if len(data) != expected:
        raise RuntimeError(f"embedding response has {len(data)} vectors, expected {expected}")
    indexes = [d.get("index", 0) for d in data]
    if sorted(indexes) == list(range(expected)):
        data = [d for _, d in sorted(zip(indexes, data, strict=True), key=lambda p: p[0])]
    return [d["embedding"] for d in data]


class OpenAIEmbedder:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        dimensions: int,
        base_url: str = "https://api.openai.com/v1",
        batch_size: int = 64,
        client: httpx.Client | None = None,
        max_retries: int = 3,
        retry_base_delay: float = 1.0,
    ) -> None:
        self._max_retries = max_retries
        self._retry_base = retry_base_delay
        self.dimensions = dimensions
        self._model = model
        self._url = f"{base_url.rstrip('/')}/embeddings"
        self._batch = batch_size
        self._client = client or httpx.Client(timeout=60)
        self._headers = {"Authorization": f"Bearer {api_key}"}

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for i in range(0, len(texts), self._batch):
            batch = texts[i : i + self._batch]
            payload = {"model": self._model, "input": batch, "dimensions": self.dimensions}
            for attempt in range(self._max_retries + 1):
                resp = self._client.post(self._url, json=payload, headers=self._headers)
                if resp.status_code not in RETRYABLE_STATUS or attempt == self._max_retries:
                    break
                time.sleep(backoff(attempt + 1, self._retry_base, resp.headers.get("retry-after")))
            if resp.status_code >= 400:
                # Status only: response bodies can echo input text.
                raise RuntimeError(f"embedding request failed with status {resp.status_code}")
            vectors.extend(_ordered_embeddings(resp.json().get("data") or [], len(batch)))
        return vectors


def build_embedder(settings: Settings) -> Embedder:
    if settings.embedding_provider == "hash":
        return HashEmbedder(settings.embedding_dimensions)
    if settings.openai_api_key is None:
        raise RuntimeError("OPENAI_API_KEY is required when EMBEDDING_PROVIDER=openai")
    return OpenAIEmbedder(
        api_key=settings.openai_api_key.get_secret_value(),
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
        base_url=settings.openai_base_url,
    )
