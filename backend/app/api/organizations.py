"""Organization, membership and invitation endpoints (/v1)."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status
from psycopg import errors

from app.auth.dependencies import DB, CurrentUser, Org
from app.repositories import tenants as repo
from app.schemas.tenants import (
    InvitationAccept,
    InvitationCreate,
    InvitationCreated,
    InvitationOut,
    MemberOut,
    MemberRoleUpdate,
    OrganizationCreate,
    OrganizationOut,
)
from app.tenants.rules import RoleRuleError, check_invite, check_revoke, check_role_change

router = APIRouter(prefix="/v1", tags=["organizations"])


def _forbidden(exc: RoleRuleError) -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, detail=str(exc))


# ---------- organizations ----------


@router.post("/organizations", status_code=status.HTTP_201_CREATED)
async def create_organization(
    body: OrganizationCreate, user: CurrentUser, db: DB
) -> OrganizationOut:
    try:
        async with db.transaction() as conn:
            org_id = await repo.create_organization(conn, body.name, body.slug)
            org = await repo.get_organization(conn, org_id, user.user_id)
    except errors.UniqueViolation:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="slug already taken") from None
    return OrganizationOut(**org)


@router.get("/organizations")
async def list_organizations(user: CurrentUser, db: DB) -> list[OrganizationOut]:
    async with db.transaction() as conn:
        rows = await repo.list_organizations(conn, user.user_id)
    return [OrganizationOut(**r) for r in rows]


@router.get("/organizations/{org_id}")
async def get_organization(ctx: Org, db: DB) -> OrganizationOut:
    async with db.transaction() as conn:
        org = await repo.get_organization(conn, ctx.org_id, ctx.user.user_id)
    if org is None:  # membership revoked between the two transactions
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="organization not found")
    return OrganizationOut(**org)


# ---------- members ----------


@router.get("/organizations/{org_id}/members")
async def list_members(ctx: Org, db: DB) -> list[MemberOut]:
    async with db.transaction() as conn:
        rows = await repo.list_members(conn, ctx.org_id)
    return [MemberOut(**r) for r in rows]


@router.post("/organizations/{org_id}/members", status_code=status.HTTP_201_CREATED)
async def invite_member(
    body: InvitationCreate, ctx: Org, db: DB, request: Request
) -> InvitationCreated:
    try:
        check_invite(actor_role=ctx.role, invite_role=body.role)
    except RoleRuleError as exc:
        raise _forbidden(exc) from None

    token = secrets.token_urlsafe(32)
    ttl = timedelta(hours=request.app.state.settings.invitation_ttl_hours)
    try:
        async with db.transaction() as conn:
            row = await repo.create_invitation(
                conn,
                org_id=ctx.org_id,
                email=body.email,
                role=body.role,
                token_hash=hashlib.sha256(token.encode()).hexdigest(),
                invited_by=ctx.user.user_id,
                expires_at=datetime.now(UTC) + ttl,
            )
    except errors.UniqueViolation:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="a pending invitation already exists for this email"
        ) from None
    return InvitationCreated(**row, token=token)


@router.patch("/organizations/{org_id}/members/{member_id}")
async def change_member_role(
    member_id: UUID, body: MemberRoleUpdate, ctx: Org, db: DB
) -> MemberOut:
    async with db.transaction() as conn:
        target = await repo.get_member_in_org(conn, ctx.org_id, member_id)
        if target is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="member not found")
        try:
            check_role_change(
                actor_role=ctx.role,
                actor_user_id=ctx.user.user_id,
                target_user_id=target["user_id"],
                target_role=target["role"],
                target_status=target["status"],
                new_role=body.role,
            )
        except RoleRuleError as exc:
            raise _forbidden(exc) from None
        updated = await repo.update_member_role(conn, ctx.org_id, member_id, body.role)
    if updated is None:  # RLS refused: rules changed underneath us
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="not allowed")
    return MemberOut(**updated)


@router.delete(
    "/organizations/{org_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def revoke_member(member_id: UUID, ctx: Org, db: DB) -> Response:
    async with db.transaction() as conn:
        target = await repo.get_member_in_org(conn, ctx.org_id, member_id)
        if target is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="member not found")
        try:
            check_revoke(
                actor_role=ctx.role,
                actor_user_id=ctx.user.user_id,
                target_user_id=target["user_id"],
                target_role=target["role"],
            )
        except RoleRuleError as exc:
            raise _forbidden(exc) from None
        if target["status"] == "revoked":
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        revoked = await repo.revoke_member(conn, ctx.org_id, member_id)
    if revoked is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="not allowed")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- invitations ----------


@router.get("/organizations/{org_id}/invitations")
async def list_invitations(ctx: Org, db: DB) -> list[InvitationOut]:
    if not ctx.is_manager:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="only owners and admins")
    async with db.transaction() as conn:
        rows = await repo.list_invitations(conn, ctx.org_id)
    return [InvitationOut(**r) for r in rows]


@router.post("/invitations/accept")
async def accept_invitation(body: InvitationAccept, db: DB) -> MemberOut:
    try:
        async with db.transaction() as conn:
            member_id = await repo.accept_invitation(conn, body.token)
            member = await repo.get_member(conn, member_id)
    except errors.NoDataFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="invitation not found") from None
    except errors.UniqueViolation:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="already a member") from None
    return MemberOut(**member)
