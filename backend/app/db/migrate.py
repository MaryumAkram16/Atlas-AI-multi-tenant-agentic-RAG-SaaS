"""Run Alembic migrations and configure the restricted API login role."""

from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config
from psycopg import sql

from app.db.urls import libpq_url

BACKEND_DIR = Path(__file__).resolve().parents[2]
LOGIN_ROLES = ("atlas_api", "atlas_worker")


def _config(database_url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.attributes["database_url"] = database_url
    return cfg


def upgrade(database_url: str, revision: str = "head") -> None:
    command.upgrade(_config(database_url), revision)


def downgrade(database_url: str, revision: str) -> None:
    command.downgrade(_config(database_url), revision)


def set_role_password(database_url: str, role: str, password: str) -> None:
    """Enable LOGIN for a restricted role (atlas_api / atlas_worker).

    Kept out of migrations so no credential is ever stored in the repo."""
    if role not in LOGIN_ROLES:
        raise ValueError(f"unknown login role {role!r}")
    if len(password) < 16:
        raise ValueError(f"password for {role} must be at least 16 characters")
    with psycopg.connect(libpq_url(database_url), autocommit=True) as conn:
        conn.execute(
            sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {}").format(
                sql.Identifier(role), sql.Literal(password)
            )
        )
