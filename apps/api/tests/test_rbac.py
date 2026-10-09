import pytest

from app.auth.rbac import (
    OrganizationRole,
    OrganizationType,
    Permission,
    admin_role_for_org_type,
    has_permission,
    require_permission,
    require_role_matches_org_type,
    role_matches_org_type,
)
from app.core.errors import AppError


def test_staff_cannot_manage_members() -> None:
    assert has_permission(OrganizationRole.PHARMACY_STAFF, Permission.ORG_READ)
    assert not has_permission(OrganizationRole.PHARMACY_STAFF, Permission.MEMBERS_MANAGE)
    with pytest.raises(AppError) as exc:
        require_permission(OrganizationRole.PHARMACY_STAFF, Permission.INVITES_CREATE)
    assert exc.value.status_code == 403


def test_admin_has_audit_and_invite() -> None:
    assert has_permission(OrganizationRole.PHARMACY_ADMIN, Permission.AUDIT_READ)
    assert has_permission(OrganizationRole.SUPPLIER_ADMIN, Permission.INVITES_CREATE)


def test_role_must_match_organization_type() -> None:
    assert role_matches_org_type(OrganizationRole.PHARMACY_ADMIN, OrganizationType.PHARMACY)
    assert not role_matches_org_type(OrganizationRole.PHARMACY_ADMIN, OrganizationType.SUPPLIER)
    with pytest.raises(AppError):
        require_role_matches_org_type(OrganizationRole.SUPPLIER_STAFF, OrganizationType.PHARMACY)


def test_creator_becomes_matching_admin() -> None:
    assert admin_role_for_org_type(OrganizationType.PHARMACY) == OrganizationRole.PHARMACY_ADMIN
    assert admin_role_for_org_type(OrganizationType.SUPPLIER) == OrganizationRole.SUPPLIER_ADMIN
