"""Document sharing: rename, visibility changes, grant and revoke.

Postgres (document_access + RLS) is the authority; the API adds checks on who
can be a grantee. Retrieval follows changes immediately.
"""

import psycopg
import pytest

from app.tenants.seed import ACME_ID, NOVA_ID, USERS
from tests.chat_helpers import ask
from tests.docs_helpers import docs_url, drain, upload
from tests.helpers import auth_header

pytestmark = pytest.mark.db

alice, aaron, amy, avery = USERS["alice"], USERS["aaron"], USERS["amy"], USERS["avery"]
nina, olga = USERS["nina"], USERS["olga"]

SECRET = b"# Bonus plan\n\nThe 2026 sales bonus pool is 4.5 percent of net revenue."
QUESTION = "How large is the 2026 sales bonus pool?"


@pytest.fixture
def restricted_doc(docs_api, worker):
    resp = upload(docs_api, amy, ACME_ID, "bonus.md", SECRET, visibility="restricted")
    assert resp.status_code == 202, resp.text
    drain(worker)
    return resp.json()["document"]["id"]


def perm_url(doc_id, user=None):
    return docs_url(ACME_ID, doc_id, "permissions", *([str(user.id)] if user else []))


def grant(api, by, doc_id, user, permission="read"):
    return api.put(perm_url(doc_id, user), json={"permission": permission}, headers=auth_header(by))


def visible(api, user, doc_id) -> bool:
    return api.get(docs_url(ACME_ID, doc_id), headers=auth_header(user)).status_code == 200


def test_owner_shares_and_revokes(docs_api, restricted_doc):
    assert not visible(docs_api, alice, restricted_doc)
    resp = grant(docs_api, amy, restricted_doc, alice)
    assert resp.status_code == 200, resp.text
    assert resp.json()["permission"] == "read" and resp.json()["email"] == alice.email
    assert visible(docs_api, alice, restricted_doc)
    doc = docs_api.get(docs_url(ACME_ID, restricted_doc), headers=auth_header(alice)).json()
    assert doc["access"] == "read"  # org owner, but the document ACL decides

    listed = docs_api.get(perm_url(restricted_doc), headers=auth_header(amy)).json()
    assert [p["user_id"] for p in listed] == [str(alice.id)]

    revoke = docs_api.delete(perm_url(restricted_doc, alice), headers=auth_header(amy))
    assert revoke.status_code == 204
    assert not visible(docs_api, alice, restricted_doc)
    again = docs_api.delete(perm_url(restricted_doc, alice), headers=auth_header(amy))
    assert again.status_code == 404


def test_grant_reaches_retrieval_and_revoke_removes_it(docs_api, restricted_doc):
    def answer():
        return ask(docs_api, aaron, ACME_ID, QUESTION).json()

    assert "4.5 percent" not in str(answer())
    assert grant(docs_api, amy, restricted_doc, aaron).status_code == 200
    body = answer()
    assert body["status"] == "answered" and "4.5 percent" in body["answer"]
    assert (
        docs_api.delete(perm_url(restricted_doc, aaron), headers=auth_header(amy)).status_code
        == 204
    )
    assert "4.5 percent" not in str(answer())


def test_write_grant_lets_member_share_but_viewer_gets_read_only(docs_api, restricted_doc):
    assert grant(docs_api, amy, restricted_doc, avery, "write").status_code == 422
    assert grant(docs_api, amy, restricted_doc, aaron, "write").status_code == 200
    # aaron now has write access and can share further.
    assert grant(docs_api, aaron, restricted_doc, avery).status_code == 200
    assert visible(docs_api, avery, restricted_doc)


def test_read_access_cannot_share_or_edit(docs_api, restricted_doc):
    assert grant(docs_api, amy, restricted_doc, alice).status_code == 200
    assert grant(docs_api, alice, restricted_doc, aaron).status_code == 403
    assert docs_api.get(perm_url(restricted_doc), headers=auth_header(alice)).status_code == 403
    patch = docs_api.patch(
        docs_url(ACME_ID, restricted_doc), json={"title": "x"}, headers=auth_header(alice)
    )
    assert patch.status_code == 403
    assert (
        docs_api.delete(perm_url(restricted_doc, alice), headers=auth_header(alice)).status_code
        == 403
    )


def test_no_access_looks_like_not_found(docs_api, restricted_doc):
    for user in (alice, aaron, avery):
        assert grant(docs_api, user, restricted_doc, user).status_code == 404
        assert docs_api.get(perm_url(restricted_doc), headers=auth_header(user)).status_code == 404


def test_grantee_must_be_an_active_member_of_this_org(docs_api, restricted_doc, seeded):
    assert grant(docs_api, amy, restricted_doc, nina).status_code == 404  # other tenant
    assert grant(docs_api, amy, restricted_doc, olga).status_code == 404  # no org
    assert grant(docs_api, amy, restricted_doc, amy).status_code == 422  # owner
    with psycopg.connect(seeded["admin"]) as conn:
        conn.execute(
            "UPDATE organization_members SET status = 'revoked', revoked_at = now()"
            " WHERE organization_id = %s AND user_id = %s",
            (ACME_ID, aaron.id),
        )
    assert grant(docs_api, amy, restricted_doc, aaron).status_code == 404


def test_other_tenant_cannot_touch_permissions(docs_api, restricted_doc):
    h = auth_header(nina)
    url = docs_url(NOVA_ID, restricted_doc, "permissions", str(nina.id))
    assert docs_api.put(url, json={"permission": "read"}, headers=h).status_code == 404
    assert docs_api.get(perm_url(restricted_doc), headers=h).status_code == 404
    assert docs_api.delete(perm_url(restricted_doc, amy), headers=h).status_code == 404


def test_rename_and_change_visibility(docs_api, restricted_doc):
    h = auth_header(amy)
    resp = docs_api.patch(
        docs_url(ACME_ID, restricted_doc),
        json={"title": "  Bonus plan 2026 ", "visibility": "organization"},
        headers=h,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["title"] == "Bonus plan 2026"
    assert resp.json()["access"] == "write"
    assert visible(docs_api, avery, restricted_doc)
    assert "4.5 percent" in ask(docs_api, avery, ACME_ID, QUESTION).json()["answer"]

    back = docs_api.patch(
        docs_url(ACME_ID, restricted_doc), json={"visibility": "restricted"}, headers=h
    )
    assert back.status_code == 200
    assert not visible(docs_api, avery, restricted_doc)


@pytest.mark.parametrize("body", [{}, {"title": "   "}, {"visibility": "public"}, {"title": ""}])
def test_invalid_updates_are_rejected(docs_api, restricted_doc, body):
    resp = docs_api.patch(docs_url(ACME_ID, restricted_doc), json=body, headers=auth_header(amy))
    assert resp.status_code == 422


def test_admin_can_edit_org_visible_document(docs_api, worker):
    resp = upload(docs_api, amy, ACME_ID, "handbook.md", b"# Handbook\n\nWelcome.")
    doc_id = resp.json()["document"]["id"]
    drain(worker)
    patch = docs_api.patch(
        docs_url(ACME_ID, doc_id), json={"title": "Employee handbook"}, headers=auth_header(aaron)
    )
    assert patch.status_code == 200 and patch.json()["title"] == "Employee handbook"
    viewer = docs_api.patch(
        docs_url(ACME_ID, doc_id), json={"title": "x"}, headers=auth_header(avery)
    )
    assert viewer.status_code == 403


def test_sharing_is_audited(docs_api, restricted_doc, seeded):
    grant(docs_api, amy, restricted_doc, alice)
    docs_api.delete(perm_url(restricted_doc, alice), headers=auth_header(amy))
    with psycopg.connect(seeded["admin"]) as conn:
        rows = conn.execute(
            "SELECT action, actor_id FROM audit_logs WHERE organization_id = %s"
            " AND resource_id = %s AND action LIKE 'document.permission_%%'"
            " ORDER BY id",
            (ACME_ID, restricted_doc),
        ).fetchall()
    assert [r[0] for r in rows] == ["document.permission_granted", "document.permission_revoked"]
    assert all(r[1] == amy.id for r in rows)
