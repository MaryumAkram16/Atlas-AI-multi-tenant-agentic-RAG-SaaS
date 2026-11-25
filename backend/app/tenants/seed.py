"""Synthetic seed data: two organizations, Acme and Nova.

User IDs stand in for Supabase Auth users. Locally, mint tokens for them with
`python -m app.db.manage dev-token alice@acme.example`.
"""

from dataclasses import dataclass
from uuid import UUID

import psycopg

ACME_ID = UUID("0a000000-0000-4000-8000-000000000001")
NOVA_ID = UUID("0b000000-0000-4000-8000-000000000001")


@dataclass(frozen=True)
class SeedUser:
    id: UUID
    email: str


USERS: dict[str, SeedUser] = {
    "alice": SeedUser(UUID("1a000000-0000-4000-8000-000000000001"), "alice@acme.example"),
    "aaron": SeedUser(UUID("1a000000-0000-4000-8000-000000000002"), "aaron@acme.example"),
    "amy": SeedUser(UUID("1a000000-0000-4000-8000-000000000003"), "amy@acme.example"),
    "avery": SeedUser(UUID("1a000000-0000-4000-8000-000000000004"), "avery@acme.example"),
    "nina": SeedUser(UUID("1b000000-0000-4000-8000-000000000001"), "nina@nova.example"),
    "noah": SeedUser(UUID("1b000000-0000-4000-8000-000000000002"), "noah@nova.example"),
    # Signed up, but not a member of any organization.
    "olga": SeedUser(UUID("1c000000-0000-4000-8000-000000000001"), "olga@example.com"),
}

ORGS = [
    (ACME_ID, "Acme", "acme", "alice"),
    (NOVA_ID, "Nova", "nova", "nina"),
]

MEMBERSHIPS = [
    (ACME_ID, "alice", "owner", None),
    (ACME_ID, "aaron", "admin", "alice"),
    (ACME_ID, "amy", "member", "alice"),
    (ACME_ID, "avery", "viewer", "aaron"),
    (NOVA_ID, "nina", "owner", None),
    (NOVA_ID, "noah", "member", "nina"),
]


def seed(conn: psycopg.Connection) -> None:
    """Idempotent. Runs as the migration owner (bypasses RLS); never from the API."""
    with conn.transaction():
        for org_id, name, slug, owner in ORGS:
            conn.execute(
                "INSERT INTO public.organizations (id, name, slug, created_by)"
                " VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
                (org_id, name, slug, USERS[owner].id),
            )
        for org_id, user, role, inviter in MEMBERSHIPS:
            conn.execute(
                "INSERT INTO public.organization_members"
                " (organization_id, user_id, role, status, invited_by)"
                " VALUES (%s, %s, %s, 'active', %s)"
                " ON CONFLICT (organization_id, user_id) DO UPDATE"
                " SET role = EXCLUDED.role, status = 'active', revoked_at = NULL",
                (org_id, USERS[user].id, role, USERS[inviter].id if inviter else None),
            )
