from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.auth.rbac import OrganizationRole, OrganizationType, Permission


class ProfileUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=40)


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    type: OrganizationType
    slug: str | None = Field(default=None, max_length=80)


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    status: str | None = Field(default=None, pattern="^(active|suspended)$")


class InviteCreate(BaseModel):
    role: OrganizationRole
    expires_in_hours: int = Field(default=72, ge=1, le=24 * 14)


class InviteAccept(BaseModel):
    code: str = Field(min_length=8, max_length=200)


class MemberRoleUpdate(BaseModel):
    role: OrganizationRole | None = None
    status: str | None = Field(default=None, pattern="^(active|disabled)$")


class MembershipOut(BaseModel):
    organization_id: UUID
    organization_name: str
    organization_slug: str
    organization_type: OrganizationType
    role: OrganizationRole
    status: str
    permissions: list[Permission]


class ProfileOut(BaseModel):
    user_id: UUID
    email: str | None
    full_name: str
    phone: str | None
    account_kind: str
    memberships: list[MembershipOut]


class OrganizationOut(BaseModel):
    id: UUID
    name: str
    slug: str
    type: OrganizationType
    status: str
    created_at: datetime


class MemberOut(BaseModel):
    user_id: UUID
    full_name: str
    role: OrganizationRole
    status: str


class InviteCreatedOut(BaseModel):
    organization_id: UUID
    role: OrganizationRole
    expires_at: datetime
    code: str
    join_hint: str


class AuditLogOut(BaseModel):
    id: UUID
    action: str
    resource_type: str
    resource_id: str | None
    result: str
    created_at: datetime
    metadata: dict = Field(default_factory=dict)
