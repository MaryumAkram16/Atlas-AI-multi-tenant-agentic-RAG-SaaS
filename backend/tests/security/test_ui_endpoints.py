"""Backend additions for the frontend: member emails and source previews."""

import pytest

from app.tenants.seed import ACME_ID, NOVA_ID, USERS
from tests.chat_helpers import ask, load_corpus
from tests.docs_helpers import docs_url, drain, upload
from tests.helpers import auth_header, mint_token

pytestmark = pytest.mark.db

alice, aaron, amy, nina, olga = (USERS[n] for n in ("alice", "aaron", "amy", "nina", "olga"))


def test_members_include_emails_from_the_verified_token(api):
    members = api.get(f"/v1/organizations/{ACME_ID}/members", headers=auth_header(alice)).json()
    assert {m["email"] for m in members} >= {"alice@acme.example", "amy@acme.example"}

    resp = api.post(
        f"/v1/organizations/{ACME_ID}/members",
        json={"email": olga.email, "role": "member"},
        headers=auth_header(alice),
    )
    token = resp.json()["token"]
    accepted = api.post("/v1/invitations/accept", json={"token": token}, headers=auth_header(olga))
    assert accepted.json()["email"] == olga.email


def test_new_org_owner_email_comes_from_token(api):
    h = {"Authorization": f"Bearer {mint_token(olga.id, 'Olga@Example.com')}"}
    org = api.post("/v1/organizations", json={"name": "O", "slug": "o-co"}, headers=h).json()
    members = api.get(f"/v1/organizations/{org['id']}/members", headers=h).json()
    assert [m["email"] for m in members] == ["olga@example.com"]


def test_member_emails_are_not_visible_across_tenants(api):
    assert (
        api.get(f"/v1/organizations/{ACME_ID}/members", headers=auth_header(nina)).status_code
        == 404
    )


@pytest.fixture
def cited(docs_api, worker):
    load_corpus(docs_api, worker, alice, ACME_ID, ["acme/refund-policy-2026.md"])
    body = ask(
        docs_api, alice, ACME_ID, "How many days do customers have to request a refund?"
    ).json()
    return body["citations"][0]


def preview_url(org, c):
    return docs_url(org, c["document_id"], "chunks", c["chunk_id"])


def test_source_preview_returns_the_cited_text(docs_api, cited):
    resp = docs_api.get(preview_url(ACME_ID, cited), headers=auth_header(amy))
    assert resp.status_code == 200
    body = resp.json()
    assert "7 days" in body["content"] and body["section"] == cited["section"]


def test_source_preview_is_tenant_scoped(docs_api, cited):
    h = auth_header(nina)
    assert docs_api.get(preview_url(ACME_ID, cited), headers=h).status_code == 404
    assert docs_api.get(preview_url(NOVA_ID, cited), headers=h).status_code == 404


def test_source_preview_respects_document_acls(docs_api, worker):
    data = b"# Bonus\n\nThe ZEPHYR-77 pool is 2 million USD.\n"
    doc = upload(docs_api, amy, ACME_ID, "b.md", data, visibility="restricted").json()["document"]
    drain(worker)
    body = ask(docs_api, amy, ACME_ID, "What is the ZEPHYR-77 pool?").json()
    citation = next(c for c in body["citations"] if c["document_id"] == doc["id"])
    assert docs_api.get(preview_url(ACME_ID, citation), headers=auth_header(amy)).status_code == 200
    for user in (alice, aaron):
        resp = docs_api.get(preview_url(ACME_ID, citation), headers=auth_header(user))
        assert resp.status_code == 404
