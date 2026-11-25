"""Tenant isolation enforced by Postgres itself, using the restricted roles the
API uses (atlas_api -> authenticated). These tests bypass the API entirely, so
they catch any query that forgets a tenant filter."""

import psycopg
import pytest
from psycopg import errors

from app.tenants.seed import ACME_ID, NOVA_ID, USERS
from tests.helpers import restricted_session

pytestmark = pytest.mark.db

alice, aaron, amy = USERS["alice"], USERS["aaron"], USERS["amy"]
nina, olga = USERS["nina"], USERS["olga"]


def org_ids(conn) -> set:
    return {r["id"] for r in conn.execute("SELECT id FROM organizations")}


def test_authorized_reads_succeed(seeded):
    with restricted_session(seeded["api"], alice) as conn:
        assert org_ids(conn) == {ACME_ID}
        rows = conn.execute("SELECT organization_id FROM organization_members").fetchall()
        assert len(rows) == 4 and {r["organization_id"] for r in rows} == {ACME_ID}


def test_cross_tenant_reads_and_listings_fail(seeded):
    with restricted_session(seeded["api"], nina) as conn:
        assert org_ids(conn) == {NOVA_ID}
        assert (
            conn.execute("SELECT * FROM organizations WHERE id = %s", (ACME_ID,)).fetchall() == []
        )
        assert (
            conn.execute(
                "SELECT * FROM organization_members WHERE organization_id = %s", (ACME_ID,)
            ).fetchall()
            == []
        )
        assert (
            conn.execute(
                "SELECT * FROM organization_invitations WHERE organization_id = %s", (ACME_ID,)
            ).fetchall()
            == []
        )


def test_no_identity_sees_nothing(seeded):
    with restricted_session(seeded["api"], None) as conn:
        assert conn.execute("SELECT * FROM organizations").fetchall() == []
        assert conn.execute("SELECT * FROM organization_members").fetchall() == []


def test_anon_role_has_no_table_access(seeded):
    with psycopg.connect(seeded["api"]) as conn:
        # atlas_api is not a member of anon, so it cannot even switch to it.
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute("SET ROLE anon")
    with psycopg.connect(seeded["admin"]) as conn:
        grants = conn.execute(
            "SELECT table_name, privilege_type FROM information_schema.role_table_grants"
            " WHERE grantee = 'anon' AND table_schema = 'public'"
        ).fetchall()
    assert grants == []


def test_api_login_role_has_no_direct_privileges(seeded):
    """atlas_api is NOINHERIT: without SET ROLE authenticated it can read nothing."""
    with psycopg.connect(seeded["api"]) as conn:
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute("SELECT * FROM organizations")


@pytest.mark.parametrize("role", ["service_role", "postgres", "supabase_admin"])
def test_api_login_role_cannot_escalate(seeded, role):
    with psycopg.connect(seeded["api"]) as conn:
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute(f"SET ROLE {role}")


def test_cross_tenant_writes_fail(seeded):
    with restricted_session(seeded["api"], nina) as conn:
        cur = conn.execute(
            "UPDATE organization_members SET role = 'viewer' WHERE organization_id = %s", (ACME_ID,)
        )
        assert cur.rowcount == 0
        cur = conn.execute(
            "UPDATE organization_invitations SET revoked_at = now() WHERE organization_id = %s",
            (ACME_ID,),
        )
        assert cur.rowcount == 0
    with restricted_session(seeded["api"], nina) as conn:
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute(
                "INSERT INTO organization_invitations"
                " (organization_id, email, role, token_hash, invited_by, expires_at)"
                " VALUES (%s, 'x@nova.example', 'member', 'h', %s, now() + interval '1 day')",
                (ACME_ID, nina.id),
            )


def test_cannot_join_an_org_by_inserting_a_membership(seeded):
    with restricted_session(seeded["api"], olga) as conn:
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute(
                "INSERT INTO organization_members (organization_id, user_id, role, status)"
                " VALUES (%s, %s, 'owner', 'active')",
                (ACME_ID, olga.id),
            )


def test_cannot_create_org_rows_directly(seeded):
    with restricted_session(seeded["api"], olga) as conn:
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute(
                "INSERT INTO organizations (name, slug, created_by) VALUES ('x', 'x', %s)",
                (olga.id,),
            )


def test_cannot_delete_organizations(seeded):
    with restricted_session(seeded["api"], alice) as conn:
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute("DELETE FROM organizations WHERE id = %s", (ACME_ID,))


def test_self_promotion_fails(seeded):
    for user, new_role in [(amy, "admin"), (amy, "owner"), (aaron, "owner"), (aaron, "admin")]:
        with restricted_session(seeded["api"], user) as conn:
            cur = conn.execute(
                "UPDATE organization_members SET role = %s WHERE user_id = %s", (new_role, user.id)
            )
            assert cur.rowcount == 0


def test_admin_cannot_grant_admin_or_owner(seeded):
    for new_role in ["admin", "owner"]:
        with restricted_session(seeded["api"], aaron) as conn:
            with pytest.raises(errors.InsufficientPrivilege):
                conn.execute(
                    "UPDATE organization_members SET role = %s"
                    " WHERE organization_id = %s AND user_id = %s",
                    (new_role, ACME_ID, amy.id),
                )


def test_member_cannot_change_others(seeded):
    with restricted_session(seeded["api"], amy) as conn:
        cur = conn.execute(
            "UPDATE organization_members SET role = 'viewer' WHERE organization_id = %s", (ACME_ID,)
        )
        assert cur.rowcount == 0


@pytest.mark.parametrize(
    "column,value", [("user_id", USERS["aaron"].id), ("organization_id", NOVA_ID)]
)
def test_identity_columns_are_not_updatable(seeded, column, value):
    with restricted_session(seeded["api"], alice) as conn:
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute(
                f"UPDATE organization_members SET {column} = %s WHERE user_id = %s", (value, amy.id)
            )


def test_revoked_member_loses_db_access(seeded):
    with psycopg.connect(seeded["admin"]) as conn:
        conn.execute(
            "UPDATE organization_members SET status = 'revoked', revoked_at = now()"
            " WHERE user_id = %s",
            (amy.id,),
        )
    with restricted_session(seeded["api"], amy) as conn:
        assert org_ids(conn) == set()
        assert conn.execute("SELECT * FROM organization_members").fetchall() == []


def test_accept_invitation_requires_matching_email(seeded):
    import hashlib

    token = "direct-db-test-token"
    with psycopg.connect(seeded["admin"]) as conn:
        conn.execute(
            "INSERT INTO organization_invitations"
            " (organization_id, email, role, token_hash, invited_by, expires_at)"
            " VALUES (%s, %s, 'member', %s, %s, now() + interval '1 day')",
            (ACME_ID, olga.email, hashlib.sha256(token.encode()).hexdigest(), alice.id),
        )
    with restricted_session(seeded["api"], nina) as conn:
        with pytest.raises(errors.NoDataFound):
            conn.execute("SELECT app_private.accept_invitation(%s)", (token,))
    with restricted_session(seeded["api"], olga) as conn:
        conn.execute("SELECT app_private.accept_invitation(%s)", (token,))
        assert org_ids(conn) == {ACME_ID}
