"""Public demo workspace: anonymous visitors join only the operator-chosen
organization, only as viewers, with private chats and no member emails."""

import uuid
from types import SimpleNamespace

import psycopg
import pytest

from app.tenants.seed import ACME_ID, NOVA_ID, USERS
from tests.chat_helpers import load_corpus
from tests.docs_helpers import docs_url, upload
from tests.helpers import auth_header, mint_token, restricted_session

pytestmark = pytest.mark.db

alice, amy = USERS["alice"], USERS["amy"]


def visitor():
    return SimpleNamespace(id=uuid.uuid4(), email=None)


def anon_header(v):
    return {"Authorization": f"Bearer {mint_token(v.id, None, is_anonymous=True)}"}


@pytest.fixture
def demo(seeded):
    with psycopg.connect(seeded["admin"]) as conn:
        conn.execute(
            "INSERT INTO app_private.demo_config (organization_id) VALUES (%s)", (ACME_ID,)
        )
    return ACME_ID


def join(api, v):
    return api.post("/v1/demo/join", headers=anon_header(v))


def test_visitor_joins_as_viewer_reads_and_chats(docs_api, worker, demo):
    load_corpus(docs_api, worker, amy, ACME_ID, ["acme/refund-policy-2026.md"])
    v = visitor()
    resp = join(docs_api, v)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"organization_id": str(ACME_ID)}
    assert join(docs_api, v).status_code == 200  # idempotent

    h = anon_header(v)
    orgs = docs_api.get("/v1/organizations", headers=h).json()
    assert [(o["id"], o["role"]) for o in orgs] == [(str(ACME_ID), "viewer")]
    assert docs_api.get(docs_url(ACME_ID), headers=h).json()  # sample documents
    body = docs_api.post(
        f"/v1/organizations/{ACME_ID}/chat",
        json={"question": "How many days do customers have to request a refund?"},
        headers=h,
    ).json()
    assert body["status"] == "answered" and "7 days" in body["answer"]

    # A second visitor cannot see the first visitor's chats.
    other = visitor()
    join(docs_api, other)
    convs = docs_api.get(f"/v1/organizations/{ACME_ID}/conversations", headers=anon_header(other))
    assert convs.json() == []
    detail = docs_api.get(
        f"/v1/organizations/{ACME_ID}/conversations/{body['conversation_id']}",
        headers=anon_header(other),
    )
    assert detail.status_code == 404


def test_visitor_cannot_upload_create_orgs_or_see_member_emails(docs_api, demo, seeded):
    v = visitor()
    join(docs_api, v)
    h = anon_header(v)
    up = docs_api.post(docs_url(ACME_ID), files={"file": ("x.md", b"# X\n\nx")}, headers=h)
    assert up.status_code == 403
    created = docs_api.post("/v1/organizations", json={"name": "Mine", "slug": "mine"}, headers=h)
    assert created.status_code == 403
    members = docs_api.get(f"/v1/organizations/{ACME_ID}/members", headers=h).json()
    assert [m["user_id"] for m in members] == [str(v.id)]
    assert docs_api.get(f"/v1/organizations/{NOVA_ID}/documents", headers=h).status_code == 404

    # Enforced in Postgres too.
    with restricted_session(seeded["api"], v, anonymous=True) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            conn.execute("SELECT app_private.create_organization('x', 'xx-anon')")
        n = conn.execute("SELECT count(*) AS n FROM organization_members").fetchone()["n"]
        assert n == 1


def test_signed_in_users_cannot_use_the_demo_join(docs_api, demo, seeded):
    assert docs_api.post("/v1/demo/join", headers=auth_header(USERS["nina"])).status_code == 403
    with restricted_session(seeded["api"], USERS["nina"]) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            conn.execute("SELECT app_private.join_demo()")
    orgs = docs_api.get("/v1/organizations", headers=auth_header(USERS["nina"])).json()
    assert str(ACME_ID) not in {o["id"] for o in orgs}


def test_no_demo_configured(docs_api, seeded):
    assert join(docs_api, visitor()).status_code == 404


def test_revoked_visitor_stays_out(docs_api, demo, seeded):
    v = visitor()
    join(docs_api, v)
    with psycopg.connect(seeded["admin"]) as conn:
        conn.execute(
            "UPDATE organization_members SET status = 'revoked', revoked_at = now()"
            " WHERE user_id = %s",
            (v.id,),
        )
    join(docs_api, v)
    assert docs_api.get(docs_url(ACME_ID), headers=anon_header(v)).status_code == 404


def test_owner_still_sees_all_members(docs_api, demo):
    v = visitor()
    join(docs_api, v)
    members = docs_api.get(f"/v1/organizations/{ACME_ID}/members", headers=auth_header(alice))
    assert str(v.id) in {m["user_id"] for m in members.json()}
    assert upload(docs_api, alice, ACME_ID, "ok.md", b"# OK\n\nfine").status_code == 202
