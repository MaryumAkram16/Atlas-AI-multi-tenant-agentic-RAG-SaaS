"""Tenant isolation and role rules, exercised through the HTTP API.

Seed (app/tenants/seed.py):
  Acme: alice (owner), aaron (admin), amy (member), avery (viewer)
  Nova: nina (owner), noah (member)
  olga: signed-up user with no memberships
"""

import psycopg
import pytest

from app.tenants.seed import ACME_ID, NOVA_ID, USERS
from tests.helpers import auth_header, mint_token

pytestmark = pytest.mark.db

alice, aaron, amy, avery = USERS["alice"], USERS["aaron"], USERS["amy"], USERS["avery"]
nina, noah, olga = USERS["nina"], USERS["noah"], USERS["olga"]


def members_url(org_id, member_id=None) -> str:
    base = f"/v1/organizations/{org_id}/members"
    return f"{base}/{member_id}" if member_id else base


def membership_id(seeded, org_id, user) -> str:
    with psycopg.connect(seeded["admin"]) as conn:
        row = conn.execute(
            "SELECT id FROM organization_members WHERE organization_id = %s AND user_id = %s",
            (org_id, user.id),
        ).fetchone()
    return str(row[0])


def db_role(seeded, org_id, user) -> tuple[str, str]:
    with psycopg.connect(seeded["admin"]) as conn:
        return conn.execute(
            "SELECT role, status FROM organization_members"
            " WHERE organization_id = %s AND user_id = %s",
            (org_id, user.id),
        ).fetchone()


# ---------- authentication ----------


@pytest.mark.parametrize(
    "path", ["/v1/organizations", f"/v1/organizations/{ACME_ID}", members_url(ACME_ID)]
)
def test_requires_token(api, path):
    assert api.get(path).status_code == 401
    assert api.get(path, headers={"Authorization": "Bearer junk"}).status_code == 401
    expired = mint_token(alice.id, alice.email, expires_in=-60)
    assert api.get(path, headers={"Authorization": f"Bearer {expired}"}).status_code == 401


# ---------- authorized reads ----------


def test_owner_lists_own_org(api):
    resp = api.get("/v1/organizations", headers=auth_header(alice))
    assert resp.status_code == 200
    assert [(o["id"], o["role"]) for o in resp.json()] == [(str(ACME_ID), "owner")]


@pytest.mark.parametrize("user", [alice, aaron, amy, avery])
def test_every_role_can_read_org_and_members(api, user):
    assert api.get(f"/v1/organizations/{ACME_ID}", headers=auth_header(user)).status_code == 200
    resp = api.get(members_url(ACME_ID), headers=auth_header(user))
    assert resp.status_code == 200
    assert {m["user_id"] for m in resp.json()} == {str(u.id) for u in (alice, aaron, amy, avery)}


# ---------- cross-tenant ----------


def test_cross_tenant_listing_shows_only_own_org(api):
    resp = api.get("/v1/organizations", headers=auth_header(nina))
    assert [o["id"] for o in resp.json()] == [str(NOVA_ID)]


@pytest.mark.parametrize("user", [nina, noah, olga])
def test_cross_tenant_reads_fail(api, user):
    assert api.get(f"/v1/organizations/{ACME_ID}", headers=auth_header(user)).status_code == 404
    assert api.get(members_url(ACME_ID), headers=auth_header(user)).status_code == 404


def test_cross_tenant_writes_fail(api, seeded):
    amy_id = membership_id(seeded, ACME_ID, amy)
    h = auth_header(nina)
    assert (
        api.patch(members_url(ACME_ID, amy_id), json={"role": "viewer"}, headers=h).status_code
        == 404
    )
    assert api.delete(members_url(ACME_ID, amy_id), headers=h).status_code == 404
    resp = api.post(
        members_url(ACME_ID), json={"email": "x@nova.example", "role": "member"}, headers=h
    )
    assert resp.status_code == 404
    assert db_role(seeded, ACME_ID, amy) == ("member", "active")


def test_url_org_id_tampering_fails(api, seeded):
    """An Acme admin cannot reach a Nova membership by mixing IDs in the URL."""
    noah_id = membership_id(seeded, NOVA_ID, noah)
    h = auth_header(aaron)
    # Own org in the URL, foreign member ID.
    assert (
        api.patch(members_url(ACME_ID, noah_id), json={"role": "viewer"}, headers=h).status_code
        == 404
    )
    assert api.delete(members_url(ACME_ID, noah_id), headers=h).status_code == 404
    # Foreign org in the URL.
    assert (
        api.patch(members_url(NOVA_ID, noah_id), json={"role": "viewer"}, headers=h).status_code
        == 404
    )
    assert api.get(members_url(NOVA_ID), headers=h).status_code == 404
    assert db_role(seeded, NOVA_ID, noah) == ("member", "active")


def test_client_supplied_org_id_in_body_is_ignored(api):
    resp = api.post(
        "/v1/organizations",
        json={
            "name": "Sneaky",
            "slug": "sneaky",
            "id": str(ACME_ID),
            "organization_id": str(ACME_ID),
        },
        headers=auth_header(olga),
    )
    assert resp.status_code == 201
    assert resp.json()["id"] != str(ACME_ID)


# ---------- role rules ----------


@pytest.mark.parametrize(
    "user,new_role",
    [(amy, "admin"), (avery, "member"), (aaron, "owner"), (amy, "owner"), (alice, "admin")],
)
def test_self_role_change_fails(api, seeded, user, new_role):
    before = db_role(seeded, ACME_ID, user)
    own_id = membership_id(seeded, ACME_ID, user)
    resp = api.patch(
        members_url(ACME_ID, own_id), json={"role": new_role}, headers=auth_header(user)
    )
    assert resp.status_code == 403
    assert db_role(seeded, ACME_ID, user) == before


@pytest.mark.parametrize("actor", [amy, avery])
def test_members_and_viewers_cannot_change_roles(api, seeded, actor):
    target = avery if actor is amy else amy
    before = db_role(seeded, ACME_ID, target)
    resp = api.patch(
        members_url(ACME_ID, membership_id(seeded, ACME_ID, target)),
        json={"role": "admin"},
        headers=auth_header(actor),
    )
    assert resp.status_code == 403
    assert db_role(seeded, ACME_ID, target) == before


def test_admin_cannot_grant_admin_but_owner_can(api, seeded):
    amy_id = membership_id(seeded, ACME_ID, amy)
    resp = api.patch(
        members_url(ACME_ID, amy_id), json={"role": "admin"}, headers=auth_header(aaron)
    )
    assert resp.status_code == 403
    resp = api.patch(
        members_url(ACME_ID, amy_id), json={"role": "admin"}, headers=auth_header(alice)
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"


def test_admin_can_change_viewer_to_member(api, seeded):
    avery_id = membership_id(seeded, ACME_ID, avery)
    resp = api.patch(
        members_url(ACME_ID, avery_id), json={"role": "member"}, headers=auth_header(aaron)
    )
    assert resp.status_code == 200
    assert db_role(seeded, ACME_ID, avery) == ("member", "active")


def test_invalid_role_value_rejected(api, seeded):
    avery_id = membership_id(seeded, ACME_ID, avery)
    resp = api.patch(
        members_url(ACME_ID, avery_id), json={"role": "superuser"}, headers=auth_header(alice)
    )
    assert resp.status_code == 422


def test_invite_permissions(api):
    body = {"email": "new@acme.example", "role": "member"}
    assert api.post(members_url(ACME_ID), json=body, headers=auth_header(amy)).status_code == 403
    assert api.post(members_url(ACME_ID), json=body, headers=auth_header(avery)).status_code == 403
    admin_invite = {"email": "boss@acme.example", "role": "admin"}
    assert (
        api.post(members_url(ACME_ID), json=admin_invite, headers=auth_header(aaron)).status_code
        == 403
    )
    assert api.post(members_url(ACME_ID), json=body, headers=auth_header(aaron)).status_code == 201


# ---------- revocation ----------


def test_revoked_member_loses_access(api, seeded):
    amy_h = auth_header(amy)  # the JWT stays valid; access must still go
    assert api.get(f"/v1/organizations/{ACME_ID}", headers=amy_h).status_code == 200

    resp = api.delete(
        members_url(ACME_ID, membership_id(seeded, ACME_ID, amy)), headers=auth_header(aaron)
    )
    assert resp.status_code == 204
    assert db_role(seeded, ACME_ID, amy) == ("member", "revoked")

    assert api.get("/v1/organizations", headers=amy_h).json() == []
    assert api.get(f"/v1/organizations/{ACME_ID}", headers=amy_h).status_code == 404
    assert api.get(members_url(ACME_ID), headers=amy_h).status_code == 404


def test_revoked_admin_cannot_manage_members(api, seeded):
    api.delete(
        members_url(ACME_ID, membership_id(seeded, ACME_ID, aaron)), headers=auth_header(alice)
    )
    avery_id = membership_id(seeded, ACME_ID, avery)
    resp = api.patch(
        members_url(ACME_ID, avery_id), json={"role": "member"}, headers=auth_header(aaron)
    )
    assert resp.status_code == 404
    assert db_role(seeded, ACME_ID, avery) == ("viewer", "active")


def test_admin_cannot_revoke_owner_or_admin(api, seeded):
    h = auth_header(aaron)
    assert (
        api.delete(
            members_url(ACME_ID, membership_id(seeded, ACME_ID, alice)), headers=h
        ).status_code
        == 403
    )
    assert (
        api.delete(
            members_url(ACME_ID, membership_id(seeded, ACME_ID, aaron)), headers=h
        ).status_code
        == 403
    )
    assert db_role(seeded, ACME_ID, alice) == ("owner", "active")


# ---------- organization creation and invitations ----------


def test_create_organization_makes_caller_owner(api):
    h = auth_header(olga)
    resp = api.post("/v1/organizations", json={"name": "Olga Co", "slug": "olga-co"}, headers=h)
    assert resp.status_code == 201
    org = resp.json()
    assert org["role"] == "owner"
    assert [o["id"] for o in api.get("/v1/organizations", headers=h).json()] == [org["id"]]
    dup = api.post(
        "/v1/organizations", json={"name": "Other", "slug": "olga-co"}, headers=auth_header(nina)
    )
    assert dup.status_code == 409


def test_invitation_accept_flow(api):
    resp = api.post(
        members_url(ACME_ID),
        json={"email": olga.email, "role": "viewer"},
        headers=auth_header(alice),
    )
    assert resp.status_code == 201
    token = resp.json()["token"]

    # Someone else holding the token cannot use it.
    assert (
        api.post(
            "/v1/invitations/accept", json={"token": token}, headers=auth_header(nina)
        ).status_code
        == 404
    )

    resp = api.post("/v1/invitations/accept", json={"token": token}, headers=auth_header(olga))
    assert resp.status_code == 200
    assert resp.json()["role"] == "viewer"
    assert [o["id"] for o in api.get("/v1/organizations", headers=auth_header(olga)).json()] == [
        str(ACME_ID)
    ]

    # Tokens are single use.
    assert (
        api.post(
            "/v1/invitations/accept", json={"token": token}, headers=auth_header(olga)
        ).status_code
        == 404
    )


def test_invitations_are_not_visible_to_members(api):
    api.post(
        members_url(ACME_ID),
        json={"email": "x@acme.example", "role": "member"},
        headers=auth_header(alice),
    )
    resp = api.get(f"/v1/organizations/{ACME_ID}/invitations", headers=auth_header(amy))
    assert resp.status_code == 403
    resp = api.get(f"/v1/organizations/{ACME_ID}/invitations", headers=auth_header(aaron))
    assert resp.status_code == 200
    assert all("token" not in i and "token_hash" not in i for i in resp.json())
