import uuid

from app.services.evaluations import score, summarize

D1, D2 = uuid.uuid4(), uuid.uuid4()


def case(**over):
    return {"expected_facts": [], "expected_document_ids": [], "should_abstain": False, **over}


def test_fact_and_evidence_hits():
    s = score(
        case(expected_facts=["7 Days"], expected_document_ids=[D1]),
        "answered",
        "Within 7 days [1].",
        [D1],
    )
    assert s == {
        "abstained": False,
        "fact_hit": True,
        "abstention_correct": None,
        "evidence_hit": True,
    }


def test_abstaining_on_an_answerable_case_misses_the_fact():
    s = score(case(expected_facts=["7 days"]), "insufficient_evidence", "", [])
    assert s["abstained"] and s["fact_hit"] is False and s["evidence_hit"] is None


def test_abstention_cases():
    assert score(case(should_abstain=True), "insufficient_evidence", "", [])["abstention_correct"]
    assert not score(case(should_abstain=True), "answered", "x [1]", [D1])["abstention_correct"]


def test_summary_metrics():
    c1, c2, c3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    rows = [
        {
            "case_id": c1,
            "abstained": False,
            "fact_hit": True,
            "abstention_correct": None,
            "evidence_hit": True,
            "cited_document_ids": [D1, D2],
            "latency_ms": 10,
            "prompt_tokens": 5,
            "completion_tokens": 2,
            "estimated_cost": None,
        },
        {
            "case_id": c2,
            "abstained": True,
            "fact_hit": False,
            "abstention_correct": None,
            "evidence_hit": False,
            "cited_document_ids": [],
            "latency_ms": 30,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "estimated_cost": None,
        },
        {
            "case_id": c3,
            "abstained": True,
            "fact_hit": None,
            "abstention_correct": True,
            "evidence_hit": None,
            "cited_document_ids": [],
            "latency_ms": 20,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "estimated_cost": None,
        },
    ]
    m = summarize(rows, {c1: {D1}, c2: {D1}, c3: set()})
    assert m["cases"] == 3
    assert m["fact_accuracy"] == 0.5 and m["false_abstention"] == 0.5
    assert m["abstention_accuracy"] == 1.0 and m["evidence_hit_rate"] == 0.5
    assert m["citation_precision"] == 0.5
    assert m["latency_p50_ms"] == 20 and m["prompt_tokens"] == 5
    assert m["estimated_cost"] is None
