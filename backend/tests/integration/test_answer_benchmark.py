import asyncio

import pytest

from app.evaluation.answer_benchmark import REPO, run, to_markdown
from tests.conftest import test_settings

pytestmark = pytest.mark.db


def test_answer_benchmark_runs(qdrant_url):
    settings = test_settings("postgresql://unused@127.0.0.1:1/x", qdrant_url=qdrant_url)
    result = asyncio.run(
        run(settings, REPO / "evaluations/datasets/hr_refund_v1.jsonl", REPO / "sample-data/acme")
    )
    for system in ("baseline", "agent"):
        s = result["summary"][system]
        assert s["n_answerable"] == 26 and s["n_missing"] == 4 and s["n_stale"] == 8
        assert 0 <= s["fact_accuracy"] <= 1
    assert "| Fact accuracy (answerable) |" in to_markdown(result)
