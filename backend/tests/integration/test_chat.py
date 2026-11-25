"""Baseline RAG chat: hybrid retrieval -> Postgres recheck -> grounded answer
with citations, JSON and SSE. Uses the offline extractive generator."""

import uuid

import psycopg
import pytest

from app.tenants.seed import ACME_ID, NOVA_ID, USERS
from tests.chat_helpers import ask, ask_stream, load_corpus
from tests.helpers import auth_header

pytestmark = pytest.mark.db

alice, amy, avery = USERS["alice"], USERS["amy"], USERS["avery"]

CORPUS = [
    "acme/refund-policy-2026.md",
    "acme/premium-support-policy.md",
    "acme/hr-leave-policy-2026.md",
]


@pytest.fixture
def corpus(docs_api, worker):
    return load_corpus(docs_api, worker, alice, ACME_ID, CORPUS)


def test_answer_cites_the_right_document_version_and_section(docs_api, corpus):
    resp = ask(docs_api, alice, ACME_ID, "How many days do customers have to request a refund?")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "answered"
    assert "7 days" in body["answer"]
    assert body["citations"], body
    first = body["citations"][0]
    assert first["document_id"] == corpus["acme/refund-policy-2026.md"]
    assert first["document_title"] == "refund-policy-2026"
    assert first["version"] == 1 and first["version_id"]
    assert first["section"] == "Acme Refund Policy (2026) > Eligibility"
    assert first["effective_date"] == "2026-01-01"
    assert {"page_start", "page_end", "chunk_id", "position"} <= first.keys()
    # Every [n] marker in the answer refers to a returned citation.
    positions = {c["position"] for c in body["citations"]}
    assert all(f"[{p}]" in body["answer"] for p in positions)
    assert 1 <= body["retrieval"]["used"] <= 8
    assert body["retrieval"]["authorized"] <= body["retrieval"]["candidates"] <= 20


def test_viewer_can_chat(docs_api, corpus):
    assert (
        ask(docs_api, avery, ACME_ID, "How long is parental leave?").json()["status"] == "answered"
    )


def test_document_filter_limits_sources(docs_api, corpus):
    leave = corpus["acme/hr-leave-policy-2026.md"]
    question = "How many days of annual leave do employees get?"
    body = ask(docs_api, alice, ACME_ID, question, document_ids=[leave]).json()
    assert body["citations"] and {c["document_id"] for c in body["citations"]} == {leave}


def test_unknown_document_filter_is_rejected(docs_api, corpus):
    resp = ask(docs_api, alice, ACME_ID, "Refunds?", document_ids=[str(uuid.uuid4())])
    assert resp.status_code == 404


def test_no_documents_means_insufficient_evidence_without_calling_the_llm(docs_api):
    class NoCall:
        name = "spy"

        def stream(self, messages):
            raise AssertionError("LLM must not be called without evidence")

    docs_api.app.state.llm = NoCall()
    body = ask(docs_api, alice, ACME_ID, "What is the refund window?").json()
    assert body["status"] == "insufficient_evidence"
    assert body["citations"] == []


def test_streaming_sse_events(docs_api, corpus):
    events = ask_stream(docs_api, alice, ACME_ID, "How much parental leave do parents get?")
    kinds = [k for k, _ in events]
    assert kinds[0] == "meta" and kinds[-1] == "done"
    assert "delta" in kinds and "citations" in kinds
    text = "".join(d["text"] for k, d in events if k == "delta")
    assert "16 weeks" in text
    citations = next(d for k, d in events if k == "citations")["citations"]
    assert citations[0]["section"].endswith("Parental leave")
    assert events[-1][1]["status"] == "answered"
    assert events[0][1]["conversation_id"] and events[0][1]["message_id"]


def test_conversation_is_persisted_with_citations_and_usage(docs_api, corpus, seeded):
    first = ask(docs_api, alice, ACME_ID, "How many days do customers have to request a refund?")
    conv = first.json()["conversation_id"]
    second = ask(docs_api, alice, ACME_ID, "Are gift cards refundable?", conversation_id=conv)
    assert second.json()["conversation_id"] == conv

    listed = docs_api.get(f"/v1/organizations/{ACME_ID}/conversations", headers=auth_header(alice))
    assert [c["id"] for c in listed.json()] == [conv]

    detail = docs_api.get(
        f"/v1/organizations/{ACME_ID}/conversations/{conv}", headers=auth_header(alice)
    ).json()
    roles = [m["role"] for m in detail["messages"]]
    assert roles == ["user", "assistant", "user", "assistant"]
    assistant = detail["messages"][1]
    assert assistant["status"] == "answered"
    assert assistant["citations"] == first.json()["citations"]

    with psycopg.connect(seeded["admin"]) as conn:
        rows = conn.execute(
            "SELECT kind, model, user_id FROM usage_events WHERE organization_id = %s",
            (ACME_ID,),
        ).fetchall()
    assert len(rows) == 2 and all(r[0] == "chat" and r[1] == "extractive" for r in rows)


def test_question_validation(docs_api):
    assert ask(docs_api, alice, ACME_ID, "").status_code == 422
    assert ask(docs_api, alice, ACME_ID, "x" * 2001).status_code == 422


def test_nova_gets_no_acme_evidence(docs_api, corpus):
    body = ask(docs_api, USERS["nina"], NOVA_ID, "What does REF-2026-07 say about refunds?").json()
    assert body["status"] == "insufficient_evidence" and body["citations"] == []
