"""Operational commands.

python -m app.db.manage migrate          # alembic upgrade head + enable atlas_api login
python -m app.db.manage seed             # Acme/Nova synthetic data (local/test only)
python -m app.db.manage dev-token EMAIL  # HS256 token for a seed user (local/test only)
"""

import argparse
import sys
import time

import jwt
import psycopg

from app.config import get_settings
from app.db import migrate
from app.db.urls import libpq_url
from app.tenants import seed

DEV_ENVS = {"local", "test"}


def _require_dev_env(command: str) -> None:
    env = get_settings().app_env
    if env not in DEV_ENVS:
        sys.exit(f"`{command}` is only allowed when APP_ENV is local or test (got {env!r})")


def cmd_migrate(_args: argparse.Namespace) -> None:
    settings = get_settings()
    url = settings.migration_database_url.get_secret_value()
    migrate.upgrade(url)
    for role, password in [
        ("atlas_api", settings.atlas_api_db_password),
        ("atlas_worker", settings.atlas_worker_db_password),
    ]:
        if password is None:
            print(f"no password configured for {role}; login left unchanged")
        else:
            migrate.set_role_password(url, role, password.get_secret_value())
            print(f"{role} login enabled")


def cmd_seed(_args: argparse.Namespace) -> None:
    _require_dev_env("seed")
    url = get_settings().migration_database_url.get_secret_value()
    with psycopg.connect(libpq_url(url)) as conn:
        seed.seed(conn)
    print("seeded Acme and Nova")
    for name, user in seed.USERS.items():
        print(f"  {name:6} {user.email:22} {user.id}")


def cmd_dev_token(args: argparse.Namespace) -> None:
    _require_dev_env("dev-token")
    settings = get_settings()
    if settings.supabase_jwt_secret is None:
        sys.exit("SUPABASE_JWT_SECRET is not set")
    user = next((u for u in seed.USERS.values() if u.email == args.email.lower()), None)
    if user is None:
        sys.exit(f"unknown seed user {args.email!r}")
    now = int(time.time())
    claims = {
        "sub": str(user.id),
        "email": user.email,
        "role": "authenticated",
        "aud": settings.supabase_jwt_audience,
        "iss": settings.supabase_jwt_issuer,
        "iat": now,
        "exp": now + args.ttl,
    }
    print(jwt.encode(claims, settings.supabase_jwt_secret.get_secret_value(), algorithm="HS256"))


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.db.manage")
    sub = parser.add_subparsers(required=True)
    sub.add_parser("migrate").set_defaults(func=cmd_migrate)
    sub.add_parser("seed").set_defaults(func=cmd_seed)
    token = sub.add_parser("dev-token")
    token.add_argument("email")
    token.add_argument("--ttl", type=int, default=3600, help="seconds")
    token.set_defaults(func=cmd_dev_token)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
