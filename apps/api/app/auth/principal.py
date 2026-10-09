from dataclasses import dataclass
from uuid import UUID

from app.auth.rbac import OrganizationRole, OrganizationType, Permission, has_permission
from app.core.errors import AppError


@dataclass(frozen=True)
class Membership:
    organization_id: UUID
    organization_name: str
    organization_slug: str
    organization_type: OrganizationType
    role: OrganizationRole
    status: str


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    email: str | None
    full_name: str
    phone: str | None
    account_kind: str
    memberships: tuple[Membership, ...]

    def membership(self, organization_id: UUID) -> Membership:
        for item in self.memberships:
            if item.organization_id == organization_id:
                return item
        raise AppError(404, "not_found", "Organization not found")

    def require_org_permission(self, organization_id: UUID, permission: Permission) -> Membership:
        membership = self.membership(organization_id)
        if not has_permission(membership.role, permission):
            raise AppError(403, "forbidden", "You do not have permission to perform this action")
        return membership
