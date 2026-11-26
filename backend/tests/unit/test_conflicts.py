import uuid
from datetime import date

from app.agents.tools.conflicts import (
    detect_conflicts,
    excluded_documents,
    facts,
    parse_meta,
    resolve,
)
from app.agents.tools.text import salient_terms
from app.services.answering import Evidence


def ev(title, content, eff, section="Eligibility"):
    doc = uuid.uuid5(uuid.NAMESPACE_DNS, title)
    return Evidence(
        uuid.uuid4(), doc, title, uuid.uuid5(doc, "v1"), 1, eff, section, None, None, content, 1.0
    )


R24 = ev(
    "refund-2024",
    "Customers may request a full refund within 14 days of purchase.",
    date(2024, 1, 1),
)
R26 = ev(
    "refund-2026",
    "Customers may request a full refund within 7 days of purchase.",
    date(2026, 1, 1),
)
PREM = ev(
    "premium",
    "Premium plan customers may request a refund within 10 days of purchase, overriding the "
    "standard refund window in REF-2026-07.",
    date(2026, 2, 1),
    "Premium refund exception",
)
HB = ev(
    "handbook-2023",
    "Agents may approve refunds requested within 30 days of purchase.",
    date(2023, 1, 1),
    "Refunds",
)
HEADERS = {
    R24.document_id: "Policy ID: REF-2024-01\nEffective date: 2024-01-01",
    R26.document_id: "Policy ID: REF-2026-07\nEffective date: 2026-01-01\nSupersedes: REF-2024-01",
    PREM.document_id: "Policy ID: PREM-2026-02\nEffective date: 2026-02-01",
    HB.document_id: "Document ID: CS-HB-2023\nStatus: Outdated. Retained for reference only.",
}


def metas(*evs):
    return {e.document_id: parse_meta(e, HEADERS.get(e.document_id), [e.content]) for e in evs}


def test_parse_meta_reads_precedence():
    m = metas(R26, PREM, HB)
    assert m[R26.document_id].policy_id == "REF-2026-07"
    assert m[R26.document_id].supersedes == ("REF-2024-01",)
    assert m[PREM.document_id].overrides == ("REF-2026-07",)
    assert m[HB.document_id].outdated


def test_facts_normalize_units():
    assert facts("within 14 days and 5 business days, 60 USD, 16 weeks") == {
        ("14", "day"),
        ("5", "day"),
        ("60", "usd"),
        ("16", "week"),
    }


def test_refund_example_resolution():
    evidence = [R24, R26, PREM, HB]
    m = metas(*evidence)
    q = "A premium customer bought something 8 days ago. Can they still get a refund?"
    conflicts = detect_conflicts(evidence, m, salient_terms(q))
    assert len(conflicts) == 1
    resolved = resolve(conflicts[0], m)
    status = {d.title: d.status for d in resolved.documents}
    assert status == {
        "refund-2024": "superseded",
        "refund-2026": "current",
        "premium": "exception",
        "handbook-2023": "outdated",
    }
    assert resolved.resolution == "resolved"
    assert excluded_documents([resolved]) == {R24.document_id, HB.document_id}
    assert any("supersedes" in n for n in resolved.notes)
    assert any("exception" in n for n in resolved.notes)


def test_effective_date_resolves_when_no_explicit_precedence():
    a = ev("a", "Allowance is 20 days.", date(2024, 1, 1), "Leave")
    b = ev("b", "Allowance is 25 days.", date(2025, 1, 1), "Leave")
    m = {
        a.document_id: parse_meta(a, "", [a.content]),
        b.document_id: parse_meta(b, "", [b.content]),
    }
    c = resolve(detect_conflicts([a, b], m, salient_terms("allowance"))[0], m)
    status = {d.title: (d.status, d.reason) for d in c.documents}
    assert status["b"][0] == "current"
    assert status["a"][0] == "superseded" and "inferred" in status["a"][1]
    # Inferred losers are flagged, not silently dropped from the answer.
    assert excluded_documents([c]) == set()


def test_ambiguous_without_dates_or_precedence():
    a = ev("a", "Allowance is 20 days.", None, "Leave")
    b = ev("b", "Allowance is 25 days.", None, "Leave")
    m = {
        a.document_id: parse_meta(a, "", [a.content]),
        b.document_id: parse_meta(b, "", [b.content]),
    }
    c = resolve(detect_conflicts([a, b], m, salient_terms("allowance"))[0], m)
    assert c.resolution == "ambiguous" and any("uncertainty" in n for n in c.notes)


def test_same_values_or_off_topic_are_not_conflicts():
    a = ev("a", "Refunds are paid within 5 business days.", date(2024, 1, 1))
    b = ev("b", "Refunds are paid within 5 business days.", date(2026, 1, 1))
    m = metas(a, b) | {a.document_id: parse_meta(a, "", []), b.document_id: parse_meta(b, "", [])}
    assert detect_conflicts([a, b], m, salient_terms("refund")) == []
    c = ev("c", "Laptops must use encryption within 30 days.", date(2025, 1, 1), "Devices")
    m[c.document_id] = parse_meta(c, "", [])
    assert detect_conflicts([a, c], m, salient_terms("refund")) == []


def test_one_shared_common_word_is_not_a_conflict():
    """A figure about something else must not join the refund conflict."""
    retention = ev(
        "data-retention",
        "Customer deletion requests are completed within 30 days of verification.",
        date(2025, 5, 1),
        "Acme Data Retention Policy > Deletion requests",
    )
    evidence = [R24, R26, PREM, HB, retention]
    m = metas(*evidence)
    q = "A premium customer bought something 8 days ago. Can they still get a refund?"
    (conflict,) = detect_conflicts(evidence, m, salient_terms(q))
    assert retention.document_id not in {d.document_id for d in conflict.documents}
    assert HB.document_id in {d.document_id for d in conflict.documents}
