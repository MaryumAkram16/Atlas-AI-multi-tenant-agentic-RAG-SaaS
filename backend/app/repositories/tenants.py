"""Tenant data access. Every function runs inside a UserDB transaction, so RLS
applies; explicit organization filters are kept as defence in depth."""

from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection

Row = dict[str, Any]


async def _one(conn: AsyncConnection, query: str, params: tuple) -> Row | None:
    cur = await conn.execute(query, params)
    return await cur.fetchone()


async def _all(conn: AsyncConnection, query: str, params: tuple) -> list[Row]:
    cur = await conn.execute(query, params)
    return await cur.fetchall()


# ---------- organizations ----------


async def create_organization(conn: AsyncConnection, name: str, slug: str) -> UUID:
    row = await _one(conn, "SELECT app_private.create_organization(%s, %s) AS id", (name, slug))
    return row["id"]


async def list_organizations(conn: AsyncConnection, user_id: UUID) -> list[Row]:
    return await _all(
        conn,
        """
        SELECT o.id, o.name, o.slug, o.plan, o.created_at, m.role
        FROM organizations o
        JOIN organization_members m ON m.organization_id = o.id
        WHERE m.user_id = %s AND m.status = 'active'
        ORDER BY o.name
        """,
        (user_id,),
    )


async def get_organization(conn: AsyncConnection, org_id: UUID, user_id: UUID) -> Row | None:
    return await _one(
        conn,
        """
        SELECT o.id, o.name, o.slug, o.plan, o.created_at, m.role
        FROM organizations o
        JOIN organization_members m ON m.organization_id = o.id
        WHERE o.id = %s AND m.user_id = %s AND m.status = 'active'
        """,
        (org_id, user_id),
    )


# ---------- members ----------


async def active_membership(conn: AsyncConnection, org_id: UUID, user_id: UUID) -> Row | None:
    return await _one(
        conn,
        """
        SELECT id, organization_id, user_id, email, role, status, invited_by, created_at, revoked_at
        FROM organization_members
        WHERE organization_id = %s AND user_id = %s AND status = 'active'
        """,
        (org_id, user_id),
    )


async def list_members(conn: AsyncConnection, org_id: UUID) -> list[Row]:
    return await _all(
        conn,
        """
        SELECT id, organization_id, user_id, email, role, status, invited_by, created_at, revoked_at
        FROM organization_members
        WHERE organization_id = %s
        ORDER BY created_at, id
        """,
        (org_id,),
    )


async def get_member_in_org(conn: AsyncConnection, org_id: UUID, member_id: UUID) -> Row | None:
    # Deliberately not FOR UPDATE: with RLS that applies the UPDATE policy to
    # the read and hides rows the caller can see but not change (giving 404
    # instead of 403). The following UPDATE is still checked by RLS.
    return await _one(
        conn,
        """
        SELECT id, organization_id, user_id, email, role, status, invited_by, created_at, revoked_at
        FROM organization_members
        WHERE organization_id = %s AND id = %s
        """,
        (org_id, member_id),
    )


async def get_member(conn: AsyncConnection, member_id: UUID) -> Row | None:
    return await _one(
        conn,
        """
        SELECT id, organization_id, user_id, email, role, status, invited_by, created_at, revoked_at
        FROM organization_members
        WHERE id = %s
        """,
        (member_id,),
    )


async def update_member_role(
    conn: AsyncConnection, org_id: UUID, member_id: UUID, role: str
) -> Row | None:
    return await _one(
        conn,
        """
        UPDATE organization_members SET role = %s
        WHERE organization_id = %s AND id = %s
        RETURNING id, organization_id, user_id, email, role, status, invited_by, created_at,
                  revoked_at
        """,
        (role, org_id, member_id),
    )


async def revoke_member(conn: AsyncConnection, org_id: UUID, member_id: UUID) -> Row | None:
    return await _one(
        conn,
        """
        UPDATE organization_members SET status = 'revoked', revoked_at = now()
        WHERE organization_id = %s AND id = %s
        RETURNING id, organization_id, user_id, email, role, status, invited_by, created_at,
                  revoked_at
        """,
        (org_id, member_id),
    )


# ---------- invitations ----------


async def create_invitation(
    conn: AsyncConnection,
    *,
    org_id: UUID,
    email: str,
    role: str,
    token_hash: str,
    invited_by: UUID,
    expires_at: datetime,
) -> Row:
    return await _one(
        conn,
        """
        INSERT INTO organization_invitations
            (organization_id, email, role, token_hash, invited_by, expires_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id, organization_id, email, role, invited_by, expires_at,
                  accepted_at, revoked_at, created_at
        """,
        (org_id, email, role, token_hash, invited_by, expires_at),
    )


async def list_invitations(conn: AsyncConnection, org_id: UUID) -> list[Row]:
    return await _all(
        conn,
        """
        SELECT id, organization_id, email, role, invited_by, expires_at,
               accepted_at, revoked_at, created_at
        FROM organization_invitations
        WHERE organization_id = %s
        ORDER BY created_at DESC
        """,
        (org_id,),
    )


async def accept_invitation(conn: AsyncConnection, token: str) -> UUID:
    row = await _one(conn, "SELECT app_private.accept_invitation(%s) AS id", (token,))
    return row["id"]
