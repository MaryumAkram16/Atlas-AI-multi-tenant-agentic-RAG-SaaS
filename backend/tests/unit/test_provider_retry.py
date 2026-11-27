import httpx
import pytest

from app.retrieval.embeddings import OpenAIEmbedder
from app.services.retry import backoff


def test_backoff_doubles_and_honours_short_retry_after():
    assert [backoff(n, 1.0) for n in (1, 2, 3)] == [1.0, 2.0, 4.0]
    assert backoff(1, 1.0, "3") == 3.0
    assert backoff(1, 1.0, "600") == 10.0  # capped
    assert backoff(2, 1.0, "soon") == 2.0  # unparsable header ignored


def test_embedder_retries_rate_limits_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "0"})
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1, 0.2]}]})

    emb = OpenAIEmbedder(
        api_key="k",
        model="m",
        dimensions=2,
        retry_base_delay=0,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert emb.embed(["hello"]) == [[0.1, 0.2]]
    assert calls["n"] == 2


def test_embedder_gives_up_after_bounded_retries():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503)

    emb = OpenAIEmbedder(
        api_key="k",
        model="m",
        dimensions=2,
        max_retries=2,
        retry_base_delay=0,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(RuntimeError, match="503"):
        emb.embed(["hello"])
    assert calls["n"] == 3
