from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.auth.deps import get_principal, get_store
from app.auth.principal import Principal
from app.auth.rbac import Permission, permissions_for
from app.core.errors import AppError
from app.modules.identity.schemas import (
    AuditLogOut,
    InviteAccept,
    InviteCreate,
    InviteCreatedOut,
    MemberOut,
    MemberRoleUpdate,
    MembershipOut,
    OrganizationCreate,
    OrganizationOut,
    OrganizationUpdate,
    ProfileOut,
    ProfileUpdate,
)
from app.modules.identity.store import IdentityStore

router = APIRouter(prefix="/api/v1")


def _membership_out(item) -> MembershipOut:
    return MembershipOut(
        organization_id=item.organization_id,
        organization_name=item.organization_name,
        organization_slug=item.organization_slug,
        organization_type=item.organization_type,
        role=item.role,
        status=item.status,
        permissions=sorted(permissions_for(item.role), key=lambda p: p.value),
    )


def _profile_out(principal: Principal) -> ProfileOut:
    return ProfileOut(
        user_id=principal.user_id,
        email=principal.email,
        full_name=principal.full_name,
        phone=principal.phone,
        account_kind=principal.account_kind,
        memberships=[_membership_out(m) for m in principal.memberships],
    )


@router.get("/me", response_model=ProfileOut)
async def read_me(
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    store: Annotated[IdentityStore, Depends(get_store)],
) -> ProfileOut:
    await store.write_audit(
        actor_user_id=principal.user_id,
        organization_id=None,
        action="session.me",
        resource_type="profile",
        resource_id=str(principal.user_id),
        request_id=getattr(request.state, "request_id", None),
    )
    return _profile_out(principal)


@router.patch("/me", response_model=ProfileOut)
async def update_me(
    payload: ProfileUpdate,
    principal: Annotated[Principal, Depends(get_principal)],
    store: Annotated[IdentityStore, Depends(get_store)],
) -> ProfileOut:
    await store.update_profile(principal.user_id, payload)
    updated = await store.load_principal(principal.user_id, principal.email)
    return _profile_out(updated)


@router.post("/organizations", response_model=OrganizationOut, status_code=201)
async def create_organization(
    payload: OrganizationCreate,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    store: Annotated[IdentityStore, Depends(get_store)],
) -> OrganizationOut:
    org = await store.create_organization(principal.user_id, payload)
    await store.write_audit(
        actor_user_id=principal.user_id,
        organization_id=org.id,
        action="organization.create",
        resource_type="organization",
        resource_id=str(org.id),
        request_id=getattr(request.state, "request_id", None),
        metadata={"type": org.type, "name": org.name},
    )
    return OrganizationOut(
        id=org.id, name=org.name, slug=org.slug, type=org.type, status=org.status, created_at=org.created_at
    )


@router.get("/organizations", response_model=list[OrganizationOut])
async def list_organizations(
    principal: Annotated[Principal, Depends(get_principal)],
    store: Annotated[IdentityStore, Depends(get_store)],
) -> list[OrganizationOut]:
    result: list[OrganizationOut] = []
    for membership in principal.memberships:
        org = await store.get_organization(membership.organization_id)
        if org is None:
            continue
        result.append(
            OrganizationOut(
                id=org.id,
                name=org.name,
                slug=org.slug,
                type=org.type,
                status=org.status,
                created_at=org.created_at,
            )
        )
    return result


@router.get("/organizations/{organization_id}", response_model=OrganizationOut)
async def get_organization(
    organization_id: UUID,
    principal: Annotated[Principal, Depends(get_principal)],
    store: Annotated[IdentityStore, Depends(get_store)],
) -> OrganizationOut:
    principal.require_org_permission(organization_id, Permission.ORG_READ)
    org = await store.get_organization(organization_id)
    if org is None:
        raise AppError(404, "not_found", "Organization not found")
    return OrganizationOut(
        id=org.id, name=org.name, slug=org.slug, type=org.type, status=org.status, created_at=org.created_at
    )


@router.patch("/organizations/{organization_id}", response_model=OrganizationOut)
async def update_organization(
    organization_id: UUID,
    payload: OrganizationUpdate,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    store: Annotated[IdentityStore, Depends(get_store)],
) -> OrganizationOut:
    principal.require_org_permission(organization_id, Permission.ORG_UPDATE)
    org = await store.update_organization(organization_id, payload.name, payload.status)
    await store.write_audit(
        actor_user_id=principal.user_id,
        organization_id=organization_id,
        action="organization.update",
        resource_type="organization",
        resource_id=str(organization_id),
        request_id=getattr(request.state, "request_id", None),
    )
    return OrganizationOut(
        id=org.id, name=org.name, slug=org.slug, type=org.type, status=org.status, created_at=org.created_at
    )


@router.get("/organizations/{organization_id}/members", response_model=list[MemberOut])
async def list_members(
    organization_id: UUID,
    principal: Annotated[Principal, Depends(get_principal)],
    store: Annotated[IdentityStore, Depends(get_store)],
) -> list[MemberOut]:
    principal.require_org_permission(organization_id, Permission.MEMBERS_READ)
    rows = await store.list_members(organization_id)
    return [
        MemberOut(user_id=member.user_id, full_name=name, role=member.role, status=member.status)
        for member, name in rows
    ]


@router.patch("/organizations/{organization_id}/members/{user_id}", response_model=MemberOut)
async def update_member(
    organization_id: UUID,
    user_id: UUID,
    payload: MemberRoleUpdate,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    store: Annotated[IdentityStore, Depends(get_store)],
) -> MemberOut:
    principal.require_org_permission(organization_id, Permission.MEMBERS_MANAGE)
    member = await store.update_member(organization_id, user_id, payload.role, payload.status)
    await store.write_audit(
        actor_user_id=principal.user_id,
        organization_id=organization_id,
        action="member.update",
        resource_type="organization_member",
        resource_id=str(user_id),
        request_id=getattr(request.state, "request_id", None),
        metadata={"role": member.role, "status": member.status},
    )
    return MemberOut(user_id=member.user_id, full_name="", role=member.role, status=member.status)


@router.post("/organizations/{organization_id}/invites", response_model=InviteCreatedOut, status_code=201)
async def create_invite(
    organization_id: UUID,
    payload: InviteCreate,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    store: Annotated[IdentityStore, Depends(get_store)],
) -> InviteCreatedOut:
    principal.require_org_permission(organization_id, Permission.INVITES_CREATE)
    invite = await store.create_invite(organization_id, principal.user_id, payload.role, payload.expires_in_hours)
    await store.write_audit(
        actor_user_id=principal.user_id,
        organization_id=organization_id,
        action="invite.create",
        resource_type="organization_invite",
        resource_id=str(organization_id),
        request_id=getattr(request.state, "request_id", None),
        metadata={"role": payload.role},
    )
    return InviteCreatedOut(
        organization_id=invite.organization_id,
        role=invite.role,
        expires_at=invite.expires_at,
        code=invite.code,
        join_hint="Share this one-time code. It is shown once.",
    )


@router.post("/invites/accept", response_model=OrganizationOut)
async def accept_invite(
    payload: InviteAccept,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    store: Annotated[IdentityStore, Depends(get_store)],
) -> OrganizationOut:
    org_id = await store.accept_invite(principal.user_id, payload.code)
    org = await store.get_organization(org_id)
    await store.write_audit(
        actor_user_id=principal.user_id,
        organization_id=org_id,
        action="invite.accept",
        resource_type="organization",
        resource_id=str(org_id),
        request_id=getattr(request.state, "request_id", None),
    )
    assert org is not None
    return OrganizationOut(
        id=org.id, name=org.name, slug=org.slug, type=org.type, status=org.status, created_at=org.created_at
    )


@router.get("/organizations/{organization_id}/audit-logs", response_model=list[AuditLogOut])
async def list_audit_logs(
    organization_id: UUID,
    principal: Annotated[Principal, Depends(get_principal)],
    store: Annotated[IdentityStore, Depends(get_store)],
) -> list[AuditLogOut]:
    principal.require_org_permission(organization_id, Permission.AUDIT_READ)
    rows = await store.list_audit(organization_id)
    return [
        AuditLogOut(
            id=row.id,
            action=row.action,
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            result=row.result,
            created_at=row.created_at,
            metadata=getattr(row, "metadata_", None) or {},
        )
        for row in rows
    ]
