"""Chat must never surface unauthorized text: restricted documents, other
tenants, other users' conversations, revoked members, stale index entries."""

import asyncio
import json

import psycopg
import pytest

from app.retrieval.authorize import load_authorized_chunks
from app.services.llm import ExtractiveLLM
from app.tenants.seed import ACME_ID, NOVA_ID, USERS
from tests.chat_helpers import ask, load_corpus
from tests.docs_helpers import drain, upload
from tests.helpers import auth_header

pytestmark = pytest.mark.db

alice, aaron, amy, avery = USERS["alice"], USERS["aaron"], USERS["amy"], USERS["avery"]
nina = USERS["nina"]
SECRET = b"# Bonus plan\n\nThe ZEPHYR-77 bonus pool is 2 million USD for executives.\n"


class SpyLLM(ExtractiveLLM):
    """Records every message the model receives."""

    def __init__(self):
        self.seen: list[str] = []

    def stream(self, messages):
        self.seen.extend(m["content"] for m in messages)
        return super().stream(messages)


@pytest.fixture
def restricted_doc(docs_api, worker):
    load_corpus(docs_api, worker, alice, ACME_ID, ["acme/refund-policy-2026.md"])
    resp = upload(docs_api, amy, ACME_ID, "bonus.md", SECRET, visibility="restricted")
    drain(worker)
    return resp.json()["document"]["id"]


@pytest.mark.parametrize("user", [alice, aaron, avery])
def test_private_document_never_reaches_unauthorized_members(docs_api, restricted_doc, user):
    spy = SpyLLM()
    docs_api.app.state.llm = spy
    body = ask(docs_api, user, ACME_ID, "What is the ZEPHYR-77 bonus pool?").json()
    assert restricted_doc not in {c["document_id"] for c in body["citations"]}
    assert "ZEPHYR" not in body["answer"] and "2 million" not in body["answer"]
    # The question mentions ZEPHYR-77; the restricted text itself must never be sent.
    assert not any("2 million" in m or "bonus pool is" in m for m in spy.seen)
    # Naming the document explicitly does not help either.
    resp = ask(docs_api, user, ACME_ID, "bonus?", document_ids=[restricted_doc])
    assert resp.status_code == 404


def test_owner_of_private_document_can_use_it(docs_api, restricted_doc):
    body = ask(docs_api, amy, ACME_ID, "What is the ZEPHYR-77 bonus pool?").json()
    assert restricted_doc in {c["document_id"] for c in body["citations"]}
    assert "2 million" in body["answer"]


def test_other_tenant_never_sees_acme_text(docs_api, restricted_doc):
    spy = SpyLLM()
    docs_api.app.state.llm = spy
    body = ask(docs_api, nina, NOVA_ID, "refund within 7 days REF-2026-07").json()
    assert body["citations"] == [] and spy.seen == []
    assert ask(docs_api, nina, ACME_ID, "refunds?").status_code == 404


def test_recheck_filters_chunks_even_if_upstream_lets_them_through(seeded, restricted_doc):
    """Simulate a bug that passes forbidden chunk IDs and document IDs to the
    recheck: Postgres RLS (document_access) still drops them."""
    with psycopg.connect(seeded["admin"]) as conn:
        forbidden = [
            r[0]
            for r in conn.execute(
                "SELECT id FROM document_chunks WHERE document_id = %s", (restricted_doc,)
            )
        ]
    assert forbidden

    async def run(user):
        conn = await psycopg.AsyncConnection.connect(seeded["api"])
        try:
            async with conn.transaction():
                await conn.execute("SET LOCAL ROLE authenticated")
                claims = json.dumps({"sub": str(user.id), "role": "authenticated"})
                await conn.execute("SELECT set_config('request.jwt.claims', %s, true)", (claims,))
                return await load_authorized_chunks(
                    conn, ACME_ID, forbidden, allowed_document_ids=[restricted_doc]
                )
        finally:
            await conn.close()

    assert asyncio.run(run(alice)) == []
    assert len(asyncio.run(run(amy))) == len(forbidden)


def test_recheck_drops_unpublished_and_deleting_documents(docs_api, worker, seeded):
    ids = load_corpus(docs_api, worker, alice, ACME_ID, ["acme/refund-policy-2026.md"])
    doc = ids["acme/refund-policy-2026.md"]
    # The document is being deleted; its vectors are still in Qdrant.
    with psycopg.connect(seeded["admin"]) as conn:
        conn.execute("UPDATE documents SET status = 'deleting' WHERE id = %s", (doc,))
    body = ask(docs_api, alice, ACME_ID, "refund within 7 days").json()
    assert body["status"] == "insufficient_evidence" and body["citations"] == []


def test_conversations_are_private(docs_api, restricted_doc):
    conv = ask(docs_api, alice, ACME_ID, "refund window?").json()["conversation_id"]
    url = f"/v1/organizations/{ACME_ID}/conversations/{conv}"
    for user in (amy, aaron):
        assert docs_api.get(url, headers=auth_header(user)).status_code == 404
        assert ask(docs_api, user, ACME_ID, "more?", conversation_id=conv).status_code == 404
        listed = docs_api.get(
            f"/v1/organizations/{ACME_ID}/conversations", headers=auth_header(user)
        )
        assert conv not in {c["id"] for c in listed.json()}
    nova_url = f"/v1/organizations/{NOVA_ID}/conversations/{conv}"
    assert docs_api.get(nova_url, headers=auth_header(nina)).status_code == 404
    assert ask(docs_api, nina, NOVA_ID, "more?", conversation_id=conv).status_code == 404


def test_revoked_member_cannot_chat_or_read_history(docs_api, restricted_doc, seeded):
    conv = ask(docs_api, amy, ACME_ID, "ZEPHYR-77?").json()["conversation_id"]
    with psycopg.connect(seeded["admin"]) as conn:
        conn.execute(
            "UPDATE organization_members SET status = 'revoked', revoked_at = now()"
            " WHERE user_id = %s",
            (amy.id,),
        )
    assert ask(docs_api, amy, ACME_ID, "ZEPHYR-77?").status_code == 404
    url = f"/v1/organizations/{ACME_ID}/conversations/{conv}"
    assert docs_api.get(url, headers=auth_header(amy)).status_code == 404


def test_citations_disappear_when_the_source_becomes_restricted(docs_api, worker, seeded):
    ids = load_corpus(docs_api, worker, amy, ACME_ID, ["acme/refund-policy-2026.md"])
    conv = ask(docs_api, alice, ACME_ID, "How many days to request a refund?").json()
    assert conv["citations"]
    with psycopg.connect(seeded["admin"]) as conn:
        conn.execute(
            "UPDATE documents SET visibility = 'restricted' WHERE id = %s",
            (ids["acme/refund-policy-2026.md"],),
        )
    detail = docs_api.get(
        f"/v1/organizations/{ACME_ID}/conversations/{conv['conversation_id']}",
        headers=auth_header(alice),
    ).json()
    assert detail["messages"][1]["citations"] == []


def _recheck(seeded, user, candidate_ids, allowed):
    async def run():
        conn = await psycopg.AsyncConnection.connect(seeded["api"])
        try:
            async with conn.transaction():
                await conn.execute("SET LOCAL ROLE authenticated")
                claims = json.dumps({"sub": str(user.id), "role": "authenticated"})
                await conn.execute("SELECT set_config('request.jwt.claims', %s, true)", (claims,))
                return await load_authorized_chunks(conn, ACME_ID, candidate_ids, allowed)
        finally:
            await conn.close()

    return asyncio.run(run())


def _chunk_ids(seeded, where, params):
    with psycopg.connect(seeded["admin"]) as conn:
        return [r[0] for r in conn.execute(f"SELECT id FROM document_chunks WHERE {where}", params)]


def test_recheck_rejects_stale_index_entries_directly(docs_api, worker, seeded):
    """The recheck itself (not just the Qdrant scope) drops chunks from
    superseded versions, documents being deleted, and documents outside the
    caller's requested scope, even when a stale index returns their IDs."""
    from tests.docs_helpers import upload_version
    from tests.files import sample

    ids = load_corpus(
        docs_api,
        worker,
        alice,
        ACME_ID,
        ["acme/refund-policy-2024.md", "acme/expenses-policy.md"],
    )
    refund, expenses = ids["acme/refund-policy-2024.md"], ids["acme/expenses-policy.md"]
    old_version = _chunk_ids(seeded, "document_id = %s", (refund,))
    upload_version(docs_api, alice, ACME_ID, refund, "r.md", sample("acme/refund-policy-2026.md"))
    drain(worker)
    current = _chunk_ids(
        seeded,
        "document_version_id = (SELECT current_version_id FROM documents WHERE id = %s)",
        (refund,),
    )
    assert set(old_version).isdisjoint(current)

    # Superseded version chunks are dropped; current ones pass.
    got = _recheck(seeded, alice, old_version + current, [refund])
    assert {e.chunk_id for e in got} == set(current)

    # A readable document outside the requested scope is dropped.
    expense_chunks = _chunk_ids(seeded, "document_id = %s", (expenses,))
    assert _recheck(seeded, alice, expense_chunks, [refund]) == []

    # A document being deleted is dropped even if listed as allowed.
    with psycopg.connect(seeded["admin"]) as conn:
        conn.execute("UPDATE documents SET status = 'deleting' WHERE id = %s", (expenses,))
    assert _recheck(seeded, alice, expense_chunks, [expenses]) == []
