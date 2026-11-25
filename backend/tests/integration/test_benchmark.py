"""The benchmark runs end to end and every dataset label resolves to chunks."""

import pytest

from app.evaluation.retrieval_benchmark import REPO, run, to_markdown
from tests.conftest import test_settings

pytestmark = pytest.mark.db


def test_benchmark_runs_and_labels_resolve(qdrant_url):
    settings = test_settings("postgresql://unused@127.0.0.1:1/x", qdrant_url=qdrant_url)
    result = run(
        settings,
        REPO / "evaluations/datasets/hr_refund_v1.jsonl",
        REPO / "sample-data/acme",
    )
    assert result["questions_total"] == 30
    assert result["questions_scored"] == 26
    for mode in ("dense", "sparse", "hybrid"):
        s = result["overall"][mode]
        assert s["n"] == 26 and 0 <= s["recall@5"] <= 1 and 0 <= s["mrr"] <= 1
    assert "| hybrid |" in to_markdown(result)
