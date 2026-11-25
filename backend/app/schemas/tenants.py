from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

from app.tenants.roles import InviteRole, Role

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")]
Email = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"),
    AfterValidator(str.lower),
]


class OrganizationCreate(BaseModel):
    # Unknown fields (e.g. a client-supplied id/organization_id) are dropped.
    model_config = ConfigDict(extra="ignore")

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    slug: Slug


class OrganizationOut(BaseModel):
    id: UUID
    name: str
    slug: str
    plan: str
    role: Role
    created_at: datetime


class MemberOut(BaseModel):
    id: UUID
    organization_id: UUID
    user_id: UUID
    email: str | None
    role: Role
    status: str
    invited_by: UUID | None
    created_at: datetime
    revoked_at: datetime | None


class MemberRoleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Role


class InvitationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: Email
    role: InviteRole = "member"


class InvitationOut(BaseModel):
    id: UUID
    organization_id: UUID
    email: str
    role: InviteRole
    invited_by: UUID
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class InvitationCreated(InvitationOut):
    token: str = Field(
        description="One-time acceptance token. Returned once; only its hash is stored. "
        "Email delivery is not implemented yet, so the inviter shares it."
    )


class InvitationAccept(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: Annotated[str, StringConstraints(min_length=16, max_length=200)]
