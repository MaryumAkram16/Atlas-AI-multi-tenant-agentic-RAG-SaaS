"""The agent through the API, over the full sample corpus (Postgres + Qdrant).
Generation uses the offline extractive provider."""

import re

import pytest

from app.tenants.seed import ACME_ID, USERS
from tests.chat_helpers import ask, ask_stream, load_corpus
from tests.files import SAMPLE_DATA
from tests.helpers import auth_header

pytestmark = pytest.mark.db

alice = USERS["alice"]
ALL = sorted(f"acme/{p.name}" for p in (SAMPLE_DATA / "acme").glob("*.md"))


@pytest.fixture
def corpus(docs_api, worker):
    return load_corpus(docs_api, worker, alice, ACME_ID, ALL)


def titles(body):
    return {c["document_title"] for c in body["citations"]}


def test_refund_policy_example(docs_api, corpus):
    """2024: 14 days, 2026: 7 days (supersedes 2024), premium exception: 10 days."""
    q = "A premium customer bought something 8 days ago. Can they still get a refund?"
    body = ask(docs_api, alice, ACME_ID, q).json()
    assert body["status"] == "answered", body
    assert body["evidence_status"] == "sufficient"
    assert "10 days" in body["answer"]
    assert "premium-support-policy" in titles(body)
    assert not titles(body) & {"refund-policy-2024", "customer-service-handbook-2023"}
    premium = next(c for c in body["citations"] if c["document_title"] == "premium-support-policy")
    assert premium["section"].endswith("Premium refund exception")
    assert premium["effective_date"] == "2026-02-01"

    docs = {d["title"]: d for c in body["conflicts"] for d in c["documents"]}
    assert docs["refund-policy-2024"]["status"] == "superseded"
    assert "explicit" in docs["refund-policy-2024"]["reason"]
    assert docs["refund-policy-2026"]["status"] == "current"
    assert docs["premium-support-policy"]["status"] == "exception"
    assert docs["customer-service-handbook-2023"]["status"] == "outdated"
    assert body["retrieval_attempts"] >= 1
    assert re.fullmatch(r"[0-9a-f]{32}", body["trace_id"])


def test_standard_refund_window_prefers_current_policy(docs_api, corpus):
    body = ask(
        docs_api, alice, ACME_ID, "How many days do customers have to request a refund?"
    ).json()
    assert body["status"] == "answered"
    assert "7 days" in body["answer"] and "14 days" not in body["answer"]
    assert "refund-policy-2024" not in titles(body)


def test_comparison_keeps_both_versions(docs_api, corpus):
    body = ask(docs_api, alice, ACME_ID, "How did annual leave change compared to 2024?").json()
    assert body["status"] == "answered"
    docs = {d["title"]: d["status"] for c in body["conflicts"] for d in c["documents"]}
    assert docs.get("hr-leave-policy-2024") == "superseded"
    assert docs.get("hr-leave-policy-2026") == "current"


def test_greeting_returns_directly(docs_api, corpus):
    body = ask(docs_api, alice, ACME_ID, "Hello!").json()
    assert body["status"] == "direct" and body["evidence_status"] == "not_needed"
    assert body["citations"] == [] and body["retrieval_attempts"] == 0


def test_missing_evidence_rewrites_then_abstains(docs_api, corpus):
    body = ask(
        docs_api, alice, ACME_ID, "What is the company's stock option vesting schedule?"
    ).json()
    assert body["status"] == "insufficient_evidence"
    assert body["citations"] == []
    assert body["retrieval_attempts"] == 3  # first search + 2 rewrites


def test_stream_reports_agent_steps_then_verified_answer(docs_api, corpus):
    events = ask_stream(docs_api, alice, ACME_ID, "How much is the home office equipment stipend?")
    kinds = [k for k, _ in events]
    steps = [d["node"] for k, d in events if k == "step"]
    assert steps[:4] == ["validate_context", "classify_intent", "plan_retrieval", "decompose_query"]
    assert "verify_citations" in steps and steps[-1] == "finalize_response"
    # Answer text only arrives after verification.
    assert kinds.index("delta") > kinds.index("step") + len(steps) - 1
    done = events[-1][1]
    assert done["status"] == "answered" and "400 USD" in "".join(
        d["text"] for k, d in events if k == "delta"
    )


def test_agent_details_are_persisted(docs_api, corpus, seeded):
    import psycopg

    body = ask(docs_api, alice, ACME_ID, "Hello!").json()
    with psycopg.connect(seeded["admin"]) as conn:
        status, meta = conn.execute(
            "SELECT status, metadata FROM messages WHERE id = %s", (body["message_id"],)
        ).fetchone()
    assert status == "direct"
    assert meta["trace_id"] == body["trace_id"]
    assert [t["node"] for t in meta["trace"]] == [
        "validate_context",
        "classify_intent",
        "finalize_response",
    ]
    detail = docs_api.get(
        f"/v1/organizations/{ACME_ID}/conversations/{body['conversation_id']}",
        headers=auth_header(alice),
    ).json()
    assert detail["messages"][1]["status"] == "direct"
