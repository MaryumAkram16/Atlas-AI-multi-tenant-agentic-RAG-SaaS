""" "Why this answer?": the explanation returned with answers and stored with them."""

import json

import psycopg
import pytest

from app.tenants.seed import ACME_ID, USERS
from tests.chat_helpers import ask, load_corpus
from tests.files import SAMPLE_DATA
from tests.helpers import auth_header

pytestmark = pytest.mark.db

alice = USERS["alice"]
ALL = sorted(f"acme/{p.name}" for p in (SAMPLE_DATA / "acme").glob("*.md"))


@pytest.fixture
def corpus(docs_api, worker):
    return load_corpus(docs_api, worker, alice, ACME_ID, ALL)


def conversation(api, conv_id):
    return api.get(
        f"/v1/organizations/{ACME_ID}/conversations/{conv_id}", headers=auth_header(alice)
    ).json()


def test_conflict_answer_explains_versions_and_precedence(docs_api, corpus):
    q = "A premium customer bought something 8 days ago. Can they still get a refund?"
    body = ask(docs_api, alice, ACME_ID, q).json()
    why = body["explanation"]
    assert why["abstain_reason"] is None and why["evidence_status"] == "sufficient"
    assert why["queries"][0]["reason"] == "original" and q in why["queries"][0]["queries"]
    cited = [s for s in why["sources"] if s["cited"]]
    assert "premium-support-policy" in {s["document_title"] for s in cited}
    assert all(s["version"] >= 1 and s["version_id"] for s in why["sources"])
    set_aside = {d["title"]: d["status"] for d in why["set_aside"]}
    assert set_aside.get("refund-policy-2024") == "superseded"
    assert set_aside.get("customer-service-handbook-2023") == "outdated"
    assert why["precedence_notes"]
    assert why["verification"]["checked"] and why["verification"]["ok"]
    # Stored with the message and returned when the conversation is read.
    stored = conversation(docs_api, body["conversation_id"])["messages"][1]["explanation"]
    assert stored == why


def test_abstention_explains_why(docs_api, corpus):
    body = ask(
        docs_api, alice, ACME_ID, "What is the company's stock option vesting schedule?"
    ).json()
    why = body["explanation"]
    assert body["status"] == "insufficient_evidence"
    assert why["abstain_reason"] in ("weak_evidence", "no_evidence", "model_declined")
    assert why["abstain_message"]
    assert [e["reason"] for e in why["queries"]] == ["original", "rewrite", "rewrite"]
    assert why["retrieval_attempts"] == 3


def test_follow_up_shows_the_standalone_question(docs_api, corpus):
    first = ask(
        docs_api, alice, ACME_ID, "How many unused annual leave days can be carried over?"
    ).json()
    body = ask(
        docs_api,
        alice,
        ACME_ID,
        "And when do they expire?",
        conversation_id=first["conversation_id"],
    ).json()
    why = body["explanation"]
    assert why["queries"][0]["reason"] == "follow_up"
    assert "carried over" in why["standalone_question"]


def test_explanation_holds_no_document_text(docs_api, corpus):
    body = ask(
        docs_api, alice, ACME_ID, "How many days do customers have to request a refund?"
    ).json()
    text = json.dumps(body["explanation"])
    assert "of purchase" not in text  # wording from the refund policy body


def test_explanation_hidden_when_sources_become_unreadable(docs_api, corpus, seeded):
    body = ask(
        docs_api, alice, ACME_ID, "How many days do customers have to request a refund?"
    ).json()
    with psycopg.connect(seeded["admin"]) as conn:
        conn.execute(
            "UPDATE documents SET visibility = 'restricted', owner_id = %s WHERE title = %s",
            (USERS["amy"].id, "refund-policy-2026"),
        )
    msg = conversation(docs_api, body["conversation_id"])["messages"][1]
    assert msg["explanation"] is None


def test_greeting_has_no_abstain_reason(docs_api, corpus):
    why = ask(docs_api, alice, ACME_ID, "Hello!").json()["explanation"]
    assert why["abstain_reason"] is None and why["sources"] == []
