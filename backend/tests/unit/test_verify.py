from app.agents.tools.verify import verify
from app.services.answering import INSUFFICIENT_EVIDENCE_ANSWER

SOURCES = [
    "Refund Eligibility Customers may request a full refund within 7 days of purchase.",
    "Premium Premium plan customers may request a refund within 10 days of purchase.",
]


def test_supported_answer_passes():
    v = verify("Standard customers have 7 days [1]. Premium customers have 10 days [2].", SOURCES)
    assert v.ok and len(v.supported) == 2


def test_uncited_claim_fails():
    v = verify("Customers have 7 days to request a refund.", SOURCES)
    assert not v.ok and "uncited" in v.problems[0]


def test_wrong_figure_fails():
    v = verify("Customers have 14 days to request a refund [1].", SOURCES)
    assert not v.ok and "14 day" in v.problems[0]


def test_citation_to_missing_source_fails():
    assert not verify("Customers have 7 days [3].", SOURCES).ok


def test_unsupported_terms_fail():
    v = verify("Executives receive stock options and bonuses [1].", SOURCES)
    assert not v.ok


def test_abstention_is_valid():
    assert verify(INSUFFICIENT_EVIDENCE_ANSWER, SOURCES).ok


def test_partial_support_reports_supported_sentences():
    v = verify("Premium customers have 10 days [2]. Everyone else gets 30 days [1].", SOURCES)
    assert not v.ok and v.supported == ["Premium customers have 10 days [2]."]
