import asyncio
import json

import pytest

from app.evaluation.answer_benchmark import CONFIGS, REPO, run, to_markdown
from tests.conftest import test_settings

pytestmark = pytest.mark.db
DATASET = REPO / "evaluations/datasets/hr_refund_v1.jsonl"


def test_dataset_has_100_plus_labeled_questions():
    rows = [json.loads(x) for x in DATASET.read_text().splitlines() if x.strip()]
    assert len(rows) >= 100
    cats = {r["category"] for r in rows}
    assert {
        "conflicting_versions",
        "outdated",
        "missing_evidence",
        "exact_policy_id",
        "prompt_injection",
    } <= cats
    assert all({"answer_facts", "stale_documents", "forbidden_strings"} <= r.keys() for r in rows)


def test_full_comparison_runs_all_configurations(qdrant_url):
    settings = test_settings("postgresql://unused@127.0.0.1:1/x", qdrant_url=qdrant_url)
    result = asyncio.run(run(settings, DATASET, REPO / "sample-data/acme"))
    assert list(result["summary"]) == list(CONFIGS)
    for name, s in result["summary"].items():
        assert s["n_answerable"] >= 80, name
        assert 0 <= s["fact_accuracy"] <= 1
    full, hybrid = result["summary"]["full agent"], result["summary"]["hybrid"]
    # Behavioural guarantees the agent stages exist for:
    assert full["stale_citation_rate"] <= hybrid["stale_citation_rate"]
    assert full["correct_abstention_rate"] >= hybrid["correct_abstention_rate"]
    assert "| Fact accuracy (answerable) |" in to_markdown(result)
