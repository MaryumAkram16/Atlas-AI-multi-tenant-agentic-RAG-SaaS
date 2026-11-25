"""Audit logs: written by database triggers for sensitive actions, readable by
owners/admins only, immutable, and free of document text and emails."""

import json

import psycopg
import pytest

from app.tenants.seed import ACME_ID, USERS
from tests.chat_helpers import load_corpus
from tests.docs_helpers import docs_url, drain
from tests.helpers import auth_header, mint_token, restricted_session

pytestmark = pytest.mark.db

alice, aaron, amy, avery, nina, olga = (
    USERS[n] for n in ("alice", "aaron", "amy", "avery", "nina", "olga")
)


def logs(api, user, **params):
    return api.get(
        f"/v1/organizations/{ACME_ID}/audit-logs", params=params, headers=auth_header(user)
    )


def actions(api, user=alice):
    return [(e["action"], e["actor_type"], e["actor_id"]) for e in logs(api, user).json()]


def test_member_and_invitation_changes_are_audited(api, seeded):
    members = api.get(f"/v1/organizations/{ACME_ID}/members", headers=auth_header(alice)).json()
    avery_id = next(m["id"] for m in members if m["user_id"] == str(avery.id))
    amy_id = next(m["id"] for m in members if m["user_id"] == str(amy.id))
    api.patch(
        f"/v1/organizations/{ACME_ID}/members/{avery_id}",
        json={"role": "member"},
        headers=auth_header(aaron),
    )
    api.delete(f"/v1/organizations/{ACME_ID}/members/{amy_id}", headers=auth_header(alice))
    token = api.post(
        f"/v1/organizations/{ACME_ID}/members",
        json={"email": olga.email, "role": "viewer"},
        headers=auth_header(alice),
    ).json()["token"]
    api.post("/v1/invitations/accept", json={"token": token}, headers=auth_header(olga))

    entries = logs(api, alice).json()
    by_action: dict = {}
    for e in entries:  # newest first: keep the most recent of each action
        by_action.setdefault(e["action"], e)
    assert by_action["member.role_changed"]["actor_id"] == str(aaron.id)
    assert by_action["member.role_changed"]["metadata"] == {
        "user_id": str(avery.id),
        "from": "viewer",
        "to": "member",
    }
    assert by_action["member.revoked"]["actor_id"] == str(alice.id)
    assert by_action["invitation.created"]["metadata"] == {"role": "viewer"}
    assert by_action["invitation.accepted"]["actor_id"] == str(olga.id)
    assert by_action["member.joined"]["actor_id"] == str(olga.id)
    # No emails or tokens in audit metadata.
    assert "@" not in json.dumps([e["metadata"] for e in entries])
    assert token not in json.dumps(entries)


def test_document_lifecycle_is_audited(docs_api, worker):
    ids = load_corpus(docs_api, worker, amy, ACME_ID, ["acme/refund-policy-2026.md"])
    doc = ids["acme/refund-policy-2026.md"]
    docs_api.post(docs_url(ACME_ID, doc, "reindex"), headers=auth_header(alice))
    drain(worker)
    docs_api.delete(docs_url(ACME_ID, doc), headers=auth_header(alice))
    drain(worker)
    seen = actions(docs_api)
    assert ("document.created", "user", str(amy.id)) in seen
    assert ("document.version_uploaded", "user", str(amy.id)) in seen
    assert ("document.version_published", "system", None) in seen
    assert ("document.reindex_requested", "user", str(alice.id)) in seen
    assert ("document.deletion_requested", "user", str(alice.id)) in seen
    assert ("document.deleted", "system", None) in seen
    text = json.dumps(logs(docs_api, alice).json())
    assert "Customers may request" not in text  # never document content


def test_new_organization_is_audited(api):
    h = {"Authorization": f"Bearer {mint_token(olga.id, olga.email)}"}
    org = api.post(
        "/v1/organizations", json={"name": "Audit Co", "slug": "audit-co"}, headers=h
    ).json()
    entries = api.get(f"/v1/organizations/{org['id']}/audit-logs", headers=h).json()
    assert [e["action"] for e in entries][-2:] == ["member.joined", "organization.created"]


@pytest.mark.parametrize("user", [amy, avery])
def test_members_and_viewers_cannot_read_audit_logs(api, user):
    assert logs(api, user).status_code == 403


def test_other_tenants_cannot_read_audit_logs(api):
    assert logs(api, nina).status_code == 404


def test_audit_logs_are_immutable_and_unreadable_directly(seeded, api):
    api.post(
        f"/v1/organizations/{ACME_ID}/members",
        json={"email": "x@acme.example", "role": "member"},
        headers=auth_header(alice),
    )
    for user in (amy, nina):
        with restricted_session(seeded["api"], user) as conn:
            rows = conn.execute(
                "SELECT * FROM audit_logs WHERE organization_id = %s", (ACME_ID,)
            ).fetchall()
            assert rows == []  # amy is a member; nina owns Nova, not Acme
    for stmt in [
        "UPDATE audit_logs SET action = 'x'",
        "DELETE FROM audit_logs",
        f"INSERT INTO audit_logs (organization_id, actor_type, action, resource_type) "
        f"VALUES ('{ACME_ID}', 'user', 'forged', 'x')",
    ]:
        with (
            restricted_session(seeded["api"], alice) as conn,
            pytest.raises(psycopg.errors.InsufficientPrivilege),
        ):
            conn.execute(stmt)


def test_audit_pagination(api):
    for i in range(3):
        api.post(
            f"/v1/organizations/{ACME_ID}/members",
            json={"email": f"p{i}@acme.example", "role": "member"},
            headers=auth_header(alice),
        )
    first = logs(api, alice, limit=2).json()
    assert len(first) == 2
    older = logs(api, alice, limit=2, before_id=first[-1]["id"]).json()
    assert older and all(e["id"] < first[-1]["id"] for e in older)
    only = logs(api, alice, action="invitation.created").json()
    assert {e["action"] for e in only} == {"invitation.created"}
