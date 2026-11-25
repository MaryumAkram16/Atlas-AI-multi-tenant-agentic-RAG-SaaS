"""Migrations run from scratch, downgrade cleanly, and leave RLS in place."""

import psycopg
import pytest
from sqlalchemy.engine import make_url

from app.db import migrate

pytestmark = pytest.mark.db

TENANT_TABLES = [
    "organizations",
    "organization_members",
    "organization_invitations",
    "documents",
    "document_versions",
    "document_permissions",
    "document_chunks",
    "ingestion_jobs",
]
DB = "atlas_migration_check"


@pytest.fixture
def scratch_db(admin_url):
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{DB}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{DB}"')
    yield make_url(admin_url).set(database=DB).render_as_string(hide_password=False)
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{DB}" WITH (FORCE)')


def tables(url) -> set[str]:
    with psycopg.connect(url) as conn:
        rows = conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        ).fetchall()
    return {r[0] for r in rows}


def test_upgrade_downgrade_upgrade(scratch_db):
    migrate.upgrade(scratch_db)
    assert set(TENANT_TABLES) <= tables(scratch_db)
    migrate.downgrade(scratch_db, "base")
    assert not set(TENANT_TABLES) & tables(scratch_db)
    migrate.upgrade(scratch_db)
    assert set(TENANT_TABLES) <= tables(scratch_db)


def test_every_tenant_table_has_rls_and_per_command_policies(test_db):
    with psycopg.connect(test_db["admin"]) as conn:
        for table in TENANT_TABLES:
            (rls,) = conn.execute(
                "SELECT relrowsecurity FROM pg_class WHERE oid = %s::regclass", (f"public.{table}",)
            ).fetchone()
            assert rls, f"RLS disabled on {table}"
            # API requests run as `authenticated`; the worker has its own
            # tenant-pinned policies, checked in the security tests.
            policies = conn.execute(
                "SELECT cmd, qual, with_check FROM pg_policies"
                " WHERE schemaname = 'public' AND tablename = %s"
                " AND roles = '{authenticated}'",
                (table,),
            ).fetchall()
            cmds = sorted(p[0] for p in policies)
            assert cmds == ["DELETE", "INSERT", "SELECT", "UPDATE"], f"{table}: {cmds}"
            for cmd, qual, with_check in policies:
                if cmd in ("INSERT", "UPDATE"):
                    assert with_check is not None, f"{table} {cmd} policy lacks WITH CHECK"
                if cmd in ("SELECT", "UPDATE", "DELETE"):
                    assert qual is not None, f"{table} {cmd} policy lacks USING"
