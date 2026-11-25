import json
import math

import httpx

from app.retrieval.embeddings import HashEmbedder, OpenAIEmbedder


def test_hash_embedder_is_deterministic_and_normalized():
    emb = HashEmbedder(dimensions=64)
    a, b = emb.embed(["refund policy", "refund policy"])
    assert a == b and len(a) == 64
    assert math.isclose(sum(x * x for x in a), 1.0, rel_tol=1e-6)
    assert emb.embed(["refund"])[0] != emb.embed(["gift card"])[0]


def test_openai_embedder_batches_and_orders():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "text-embedding-3-small" and body["dimensions"] == 3
        assert request.headers["authorization"] == "Bearer sk-test"
        data = [{"index": i, "embedding": [float(i)] * 3} for i in range(len(body["input"]))]
        return httpx.Response(200, json={"data": list(reversed(data))})

    emb = OpenAIEmbedder(
        api_key="sk-test",
        model="text-embedding-3-small",
        dimensions=3,
        batch_size=2,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    vectors = emb.embed(["a", "b", "c"])
    assert vectors == [[0.0] * 3, [1.0] * 3, [0.0] * 3]  # two batches: [a, b], [c]
