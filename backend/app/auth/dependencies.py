"""Request authentication and organization membership checks.

Every protected route depends on `current_user` (JWT verified on each request)
and org-scoped routes on `org_member`, which confirms an *active* membership in
Postgres for the org in the URL. A client-supplied org ID is never trusted on
its own: non-members get 404 so org existence is not revealed.
"""

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.jwt import AuthError, AuthUser, JWTVerifier
from app.db.session import UserDB
from app.repositories import tenants as repo
from app.tenants.roles import MANAGERS

_bearer = HTTPBearer(auto_error=False)


async def current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AuthUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()
    verifier: JWTVerifier = request.app.state.jwt_verifier
    try:
        return verifier.verify(credentials.credentials)
    except AuthError:
        raise _unauthorized() from None


def _unauthorized() -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        detail="invalid or missing credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


CurrentUser = Annotated[AuthUser, Depends(current_user)]


def user_db(request: Request, user: CurrentUser) -> UserDB:
    return UserDB(request.app.state.db_pool, user)


DB = Annotated[UserDB, Depends(user_db)]


@dataclass(frozen=True)
class OrgContext:
    org_id: UUID
    user: AuthUser
    role: str
    membership_id: UUID

    @property
    def is_manager(self) -> bool:
        return self.role in MANAGERS


async def org_member(org_id: UUID, user: CurrentUser, db: DB) -> OrgContext:
    async with db.transaction() as conn:
        membership = await repo.active_membership(conn, org_id, user.user_id)
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="organization not found")
    return OrgContext(
        org_id=org_id, user=user, role=membership["role"], membership_id=membership["id"]
    )


Org = Annotated[OrgContext, Depends(org_member)]
