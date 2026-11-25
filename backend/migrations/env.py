"""Alembic environment. Migrations are plain SQL (no ORM models)."""

from alembic import context
from sqlalchemy import create_engine, pool

from app.db.urls import sqlalchemy_url

config = context.config


def _url() -> str:
    # Tests and the manage CLI pass an explicit URL; otherwise use settings.
    url = config.attributes.get("database_url")
    if url is None:
        from app.config import get_settings

        url = get_settings().migration_database_url.get_secret_value()
    return sqlalchemy_url(url)


def run_migrations_offline() -> None:
    context.configure(url=_url(), literal_binds=True, transaction_per_migration=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
