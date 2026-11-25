"""When access to a source is lost, stored answers that used it are hidden,
their citations disappear, and they are no longer reused as chat history."""

import psycopg
import pytest

from app.repositories.chat import REDACTED_ANSWER
from app.services.llm import ExtractiveLLM
from app.tenants.seed import ACME_ID, USERS
from tests.chat_helpers import ask, load_corpus
from tests.helpers import auth_header

pytestmark = pytest.mark.db

alice, amy = USERS["alice"], USERS["amy"]


class SpyLLM(ExtractiveLLM):
    def __init__(self):
        self.messages: list[list[dict]] = []

    def stream(self, messages):
        self.messages.append(messages)
        return super().stream(messages)


@pytest.fixture
def answered(docs_api, worker):
    ids = load_corpus(docs_api, worker, amy, ACME_ID, ["acme/refund-policy-2026.md"])
    body = ask(docs_api, alice, ACME_ID, "How many days do customers have to request a refund?")
    return ids["acme/refund-policy-2026.md"], body.json()


def conversation(docs_api, conv_id):
    return docs_api.get(
        f"/v1/organizations/{ACME_ID}/conversations/{conv_id}", headers=auth_header(alice)
    ).json()


def test_answer_hidden_after_source_becomes_restricted(docs_api, answered, seeded):
    doc, body = answered
    assert "7 days" in conversation(docs_api, body["conversation_id"])["messages"][1]["content"]
    with psycopg.connect(seeded["admin"]) as conn:
        conn.execute("UPDATE documents SET visibility = 'restricted' WHERE id = %s", (doc,))
    msg = conversation(docs_api, body["conversation_id"])["messages"][1]
    assert msg["content"] == REDACTED_ANSWER
    assert msg["citations"] == [] and msg["conflicts"] == []


def test_hidden_answer_is_not_reused_as_history(docs_api, worker, answered, seeded):
    doc, body = answered
    # A second, still-readable source so the follow-up reaches the model.
    load_corpus(docs_api, worker, amy, ACME_ID, ["acme/expenses-policy.md"])
    with psycopg.connect(seeded["admin"]) as conn:
        conn.execute("UPDATE documents SET visibility = 'restricted' WHERE id = %s", (doc,))
    spy = SpyLLM()
    docs_api.app.state.llm = spy
    follow = ask(
        docs_api,
        alice,
        ACME_ID,
        "How much are meal expenses reimbursed during business travel?",
        conversation_id=body["conversation_id"],
    ).json()
    assert follow["status"] == "answered" and spy.messages, "the model must have been called"
    for messages in spy.messages:
        history = messages[1:-1]
        assert history, "earlier turns are passed as history"
        assert not any("7 days of purchase" in m["content"] for m in history)
        assert any(m["content"] == REDACTED_ANSWER for m in history)


def test_answer_hidden_after_source_deleted(docs_api, worker, answered):
    doc, body = answered
    docs_api.delete(f"/v1/organizations/{ACME_ID}/documents/{doc}", headers=auth_header(amy))
    from tests.docs_helpers import drain

    drain(worker)
    assert (
        conversation(docs_api, body["conversation_id"])["messages"][1]["content"] == REDACTED_ANSWER
    )


def test_answers_stay_visible_while_access_remains(docs_api, answered):
    _, body = answered
    msg = conversation(docs_api, body["conversation_id"])["messages"][1]
    assert msg["content"] != REDACTED_ANSWER and msg["citations"]
