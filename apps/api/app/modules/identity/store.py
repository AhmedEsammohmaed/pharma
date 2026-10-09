from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Membership, Principal
from app.auth.rbac import (
    OrganizationRole,
    OrganizationType,
    admin_role_for_org_type,
    require_role_matches_org_type,
)
from app.core.errors import AppError
from app.modules.identity.models import (
    AuditLog,
    Organization,
    OrganizationInvite,
    OrganizationMember,
    Profile,
)
from app.modules.identity.schemas import OrganizationCreate, ProfileUpdate


def slugify(name: str, suffix: str | None = None) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "org"
    token = suffix if suffix is not None else secrets.token_hex(3)
    return f"{base}-{token}"


def hash_invite_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def new_invite_code() -> str:
    return secrets.token_urlsafe(18)


@dataclass
class InviteIssue:
    organization_id: UUID
    role: OrganizationRole
    expires_at: datetime
    code: str


class IdentityStore(Protocol):
    async def ensure_profile(self, user_id: UUID, full_name: str = "", account_kind: str = "customer") -> None: ...
    async def load_principal(self, user_id: UUID, email: str | None) -> Principal: ...
    async def update_profile(self, user_id: UUID, patch: ProfileUpdate) -> None: ...
    async def create_organization(self, user_id: UUID, payload: OrganizationCreate) -> Organization: ...
    async def get_organization(self, organization_id: UUID) -> Organization | None: ...
    async def update_organization(self, organization_id: UUID, name: str | None, status: str | None) -> Organization: ...
    async def list_members(self, organization_id: UUID) -> list[tuple[OrganizationMember, str]]: ...
    async def update_member(
        self, organization_id: UUID, user_id: UUID, role: OrganizationRole | None, status: str | None
    ) -> OrganizationMember: ...
    async def create_invite(
        self, organization_id: UUID, created_by: UUID, role: OrganizationRole, expires_in_hours: int
    ) -> InviteIssue: ...
    async def accept_invite(self, user_id: UUID, code: str) -> UUID: ...
    async def write_audit(
        self,
        *,
        actor_user_id: UUID | None,
        organization_id: UUID | None,
        action: str,
        resource_type: str,
        resource_id: str | None,
        result: str = "success",
        request_id: str | None = None,
        metadata: dict | None = None,
    ) -> None: ...
    async def list_audit(self, organization_id: UUID, limit: int = 50) -> list[AuditLog]: ...


class SqlIdentityStore:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def ensure_profile(self, user_id: UUID, full_name: str = "", account_kind: str = "customer") -> None:
        existing = await self.session.get(Profile, user_id)
        if existing:
            return
        self.session.add(Profile(user_id=user_id, full_name=full_name, account_kind=account_kind))
        await self.session.flush()

    async def load_principal(self, user_id: UUID, email: str | None) -> Principal:
        await self.ensure_profile(user_id)
        profile = await self.session.get(Profile, user_id)
        if profile is None or profile.deleted_at is not None:
            raise AppError(401, "unauthenticated", "Profile is not available")
        stmt = (
            select(OrganizationMember, Organization)
            .join(Organization, Organization.id == OrganizationMember.organization_id)
            .where(
                OrganizationMember.user_id == user_id,
                OrganizationMember.deleted_at.is_(None),
                OrganizationMember.status == "active",
                Organization.deleted_at.is_(None),
            )
        )
        rows = (await self.session.execute(stmt)).all()
        memberships = tuple(
            Membership(
                organization_id=org.id,
                organization_name=org.name,
                organization_slug=org.slug,
                organization_type=OrganizationType(org.type),
                role=OrganizationRole(member.role),
                status=member.status,
            )
            for member, org in rows
        )
        return Principal(
            user_id=user_id,
            email=email,
            full_name=profile.full_name,
            phone=profile.phone,
            account_kind=profile.account_kind,
            memberships=memberships,
        )

    async def update_profile(self, user_id: UUID, patch: ProfileUpdate) -> None:
        profile = await self.session.get(Profile, user_id)
        if profile is None:
            raise AppError(404, "not_found", "Profile not found")
        if patch.full_name is not None:
            profile.full_name = patch.full_name.strip()
        if patch.phone is not None:
            profile.phone = patch.phone.strip() or None
        await self.session.flush()

    async def create_organization(self, user_id: UUID, payload: OrganizationCreate) -> Organization:
        if payload.type == OrganizationType.PLATFORM:
            raise AppError(403, "forbidden", "Platform organizations cannot be self-served")
        slug = payload.slug or slugify(payload.name)
        if payload.slug:
            slug = re.sub(r"[^a-z0-9-]+", "", payload.slug.lower()).strip("-")
            if not slug:
                raise AppError(422, "invalid_slug", "Slug must contain letters or numbers")
        org = Organization(
            name=payload.name.strip(),
            slug=slug,
            type=payload.type.value,
            status="active",
            created_by=user_id,
        )
        self.session.add(org)
        await self.session.flush()
        role = admin_role_for_org_type(payload.type)
        self.session.add(
            OrganizationMember(
                organization_id=org.id,
                user_id=user_id,
                role=role.value,
                status="active",
            )
        )
        profile = await self.session.get(Profile, user_id)
        if profile:
            profile.account_kind = "staff"
        await self.session.flush()
        return org

    async def get_organization(self, organization_id: UUID) -> Organization | None:
        org = await self.session.get(Organization, organization_id)
        if org is None or org.deleted_at is not None:
            return None
        return org

    async def update_organization(self, organization_id: UUID, name: str | None, status: str | None) -> Organization:
        org = await self.get_organization(organization_id)
        if org is None:
            raise AppError(404, "not_found", "Organization not found")
        if name is not None:
            org.name = name.strip()
        if status is not None:
            org.status = status
        await self.session.flush()
        return org

    async def list_members(self, organization_id: UUID) -> list[tuple[OrganizationMember, str]]:
        stmt = (
            select(OrganizationMember, Profile.full_name)
            .join(Profile, Profile.user_id == OrganizationMember.user_id)
            .where(
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.deleted_at.is_(None),
            )
        )
        return [(row[0], row[1] or "") for row in (await self.session.execute(stmt)).all()]

    async def update_member(
        self, organization_id: UUID, user_id: UUID, role: OrganizationRole | None, status: str | None
    ) -> OrganizationMember:
        stmt = select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == user_id,
            OrganizationMember.deleted_at.is_(None),
        )
        member = (await self.session.execute(stmt)).scalar_one_or_none()
        if member is None:
            raise AppError(404, "not_found", "Member not found")
        org = await self.get_organization(organization_id)
        if org is None:
            raise AppError(404, "not_found", "Organization not found")
        if role is not None:
            require_role_matches_org_type(role, OrganizationType(org.type))
            member.role = role.value
        if status is not None:
            member.status = status
        await self.session.flush()
        return member

    async def create_invite(
        self, organization_id: UUID, created_by: UUID, role: OrganizationRole, expires_in_hours: int
    ) -> InviteIssue:
        org = await self.get_organization(organization_id)
        if org is None:
            raise AppError(404, "not_found", "Organization not found")
        require_role_matches_org_type(role, OrganizationType(org.type))
        code = new_invite_code()
        expires_at = datetime.now(UTC) + timedelta(hours=expires_in_hours)
        self.session.add(
            OrganizationInvite(
                organization_id=organization_id,
                code_hash=hash_invite_code(code),
                role=role.value,
                expires_at=expires_at,
                created_by=created_by,
            )
        )
        await self.session.flush()
        return InviteIssue(organization_id=organization_id, role=role, expires_at=expires_at, code=code)

    async def accept_invite(self, user_id: UUID, code: str) -> UUID:
        code_hash = hash_invite_code(code)
        context_user_id = (await self.session.execute(text("SELECT app.current_user_id()"))).scalar_one_or_none()
        if context_user_id is None or UUID(str(context_user_id)) != user_id:
            raise AppError(401, "unauthenticated", "Invite acceptance context is invalid")
        # Acceptance is performed by the row-locking database function so concurrent
        # requests cannot consume the same invite twice.
        result = await self.session.execute(
            text("SELECT app.accept_organization_invite(:code_hash)"),
            {"code_hash": code_hash},
        )
        org_id = result.scalar_one()
        await self.session.flush()
        return UUID(str(org_id))

    async def write_audit(
        self,
        *,
        actor_user_id: UUID | None,
        organization_id: UUID | None,
        action: str,
        resource_type: str,
        resource_id: str | None,
        result: str = "success",
        request_id: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        self.session.add(
            AuditLog(
                organization_id=organization_id,
                actor_user_id=actor_user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                result=result,
                request_id=request_id,
                metadata_=metadata or {},
            )
        )
        await self.session.flush()

    async def list_audit(self, organization_id: UUID, limit: int = 50) -> list[AuditLog]:
        stmt = (
            select(AuditLog)
            .where(AuditLog.organization_id == organization_id)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())


@dataclass
class _MemOrg:
    id: UUID
    name: str
    slug: str
    type: str
    status: str
    created_by: UUID
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    deleted_at: datetime | None = None


@dataclass
class _MemMember:
    organization_id: UUID
    user_id: UUID
    role: str
    status: str = "active"
    deleted_at: datetime | None = None


@dataclass
class _MemProfile:
    user_id: UUID
    full_name: str = ""
    phone: str | None = None
    account_kind: str = "customer"
    deleted_at: datetime | None = None


@dataclass
class _MemInvite:
    organization_id: UUID
    code_hash: str
    role: str
    expires_at: datetime
    created_by: UUID
    accepted_by: UUID | None = None
    accepted_at: datetime | None = None
    revoked_at: datetime | None = None


@dataclass
class _MemAudit:
    id: UUID
    organization_id: UUID | None
    actor_user_id: UUID | None
    action: str
    resource_type: str
    resource_id: str | None
    result: str
    request_id: str | None
    metadata: dict
    created_at: datetime


class MemoryIdentityStore:
    """In-memory store for authorization tests. Not used in production."""

    def __init__(self) -> None:
        self.profiles: dict[UUID, _MemProfile] = {}
        self.orgs: dict[UUID, _MemOrg] = {}
        self.members: list[_MemMember] = []
        self.invites: list[_MemInvite] = []
        self.audits: list[_MemAudit] = []

    async def ensure_profile(self, user_id: UUID, full_name: str = "", account_kind: str = "customer") -> None:
        self.profiles.setdefault(user_id, _MemProfile(user_id=user_id, full_name=full_name, account_kind=account_kind))

    async def load_principal(self, user_id: UUID, email: str | None) -> Principal:
        await self.ensure_profile(user_id)
        profile = self.profiles[user_id]
        memberships = []
        for member in self.members:
            if member.user_id != user_id or member.deleted_at or member.status != "active":
                continue
            org = self.orgs[member.organization_id]
            if org.deleted_at:
                continue
            memberships.append(
                Membership(
                    organization_id=org.id,
                    organization_name=org.name,
                    organization_slug=org.slug,
                    organization_type=OrganizationType(org.type),
                    role=OrganizationRole(member.role),
                    status=member.status,
                )
            )
        return Principal(
            user_id=user_id,
            email=email,
            full_name=profile.full_name,
            phone=profile.phone,
            account_kind=profile.account_kind,
            memberships=tuple(memberships),
        )

    async def update_profile(self, user_id: UUID, patch: ProfileUpdate) -> None:
        profile = self.profiles.get(user_id)
        if not profile:
            raise AppError(404, "not_found", "Profile not found")
        if patch.full_name is not None:
            profile.full_name = patch.full_name.strip()
        if patch.phone is not None:
            profile.phone = patch.phone.strip() or None

    async def create_organization(self, user_id: UUID, payload: OrganizationCreate) -> Organization:
        if payload.type == OrganizationType.PLATFORM:
            raise AppError(403, "forbidden", "Platform organizations cannot be self-served")
        org_id = uuid4()
        slug = payload.slug or slugify(payload.name)
        mem_org = _MemOrg(
            id=org_id,
            name=payload.name.strip(),
            slug=slug,
            type=payload.type.value,
            status="active",
            created_by=user_id,
        )
        self.orgs[org_id] = mem_org
        self.members.append(
            _MemMember(
                organization_id=org_id,
                user_id=user_id,
                role=admin_role_for_org_type(payload.type).value,
            )
        )
        if user_id in self.profiles:
            self.profiles[user_id].account_kind = "staff"
        return Organization(
            id=mem_org.id,
            name=mem_org.name,
            slug=mem_org.slug,
            type=mem_org.type,
            status=mem_org.status,
            created_by=mem_org.created_by,
            created_at=mem_org.created_at,
            updated_at=mem_org.created_at,
        )

    async def get_organization(self, organization_id: UUID) -> Organization | None:
        org = self.orgs.get(organization_id)
        if org is None or org.deleted_at:
            return None
        return Organization(
            id=org.id,
            name=org.name,
            slug=org.slug,
            type=org.type,
            status=org.status,
            created_by=org.created_by,
            created_at=org.created_at,
            updated_at=org.created_at,
        )

    async def update_organization(self, organization_id: UUID, name: str | None, status: str | None) -> Organization:
        org = self.orgs.get(organization_id)
        if org is None or org.deleted_at:
            raise AppError(404, "not_found", "Organization not found")
        if name is not None:
            org.name = name.strip()
        if status is not None:
            org.status = status
        return await self.get_organization(organization_id)  # type: ignore[return-value]

    async def list_members(self, organization_id: UUID) -> list[tuple[OrganizationMember, str]]:
        result: list[tuple[OrganizationMember, str]] = []
        for member in self.members:
            if member.organization_id != organization_id or member.deleted_at:
                continue
            name = self.profiles.get(member.user_id, _MemProfile(member.user_id)).full_name
            result.append(
                (
                    OrganizationMember(
                        organization_id=member.organization_id,
                        user_id=member.user_id,
                        role=member.role,
                        status=member.status,
                    ),
                    name,
                )
            )
        return result

    async def update_member(
        self, organization_id: UUID, user_id: UUID, role: OrganizationRole | None, status: str | None
    ) -> OrganizationMember:
        org = self.orgs.get(organization_id)
        if org is None:
            raise AppError(404, "not_found", "Organization not found")
        for member in self.members:
            if member.organization_id == organization_id and member.user_id == user_id and not member.deleted_at:
                if role is not None:
                    require_role_matches_org_type(role, OrganizationType(org.type))
                    member.role = role.value
                if status is not None:
                    member.status = status
                return OrganizationMember(
                    organization_id=member.organization_id,
                    user_id=member.user_id,
                    role=member.role,
                    status=member.status,
                )
        raise AppError(404, "not_found", "Member not found")

    async def create_invite(
        self, organization_id: UUID, created_by: UUID, role: OrganizationRole, expires_in_hours: int
    ) -> InviteIssue:
        org = self.orgs.get(organization_id)
        if org is None:
            raise AppError(404, "not_found", "Organization not found")
        require_role_matches_org_type(role, OrganizationType(org.type))
        code = new_invite_code()
        expires_at = datetime.now(UTC) + timedelta(hours=expires_in_hours)
        self.invites.append(
            _MemInvite(
                organization_id=organization_id,
                code_hash=hash_invite_code(code),
                role=role.value,
                expires_at=expires_at,
                created_by=created_by,
            )
        )
        return InviteIssue(organization_id=organization_id, role=role, expires_at=expires_at, code=code)

    async def accept_invite(self, user_id: UUID, code: str) -> UUID:
        code_hash = hash_invite_code(code)
        for invite in self.invites:
            if invite.code_hash != code_hash:
                continue
            if invite.revoked_at:
                raise AppError(404, "not_found", "Invite not found")
            if invite.accepted_at:
                raise AppError(409, "invite_used", "Invite has already been used")
            if invite.expires_at < datetime.now(UTC):
                raise AppError(410, "invite_expired", "Invite has expired")
            existing = next(
                (
                    m
                    for m in self.members
                    if m.organization_id == invite.organization_id and m.user_id == user_id
                ),
                None,
            )
            if existing:
                existing.role = invite.role
                existing.status = "active"
                existing.deleted_at = None
            else:
                self.members.append(
                    _MemMember(organization_id=invite.organization_id, user_id=user_id, role=invite.role)
                )
            invite.accepted_by = user_id
            invite.accepted_at = datetime.now(UTC)
            return invite.organization_id
        raise AppError(404, "not_found", "Invite not found")

    async def write_audit(
        self,
        *,
        actor_user_id: UUID | None,
        organization_id: UUID | None,
        action: str,
        resource_type: str,
        resource_id: str | None,
        result: str = "success",
        request_id: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        self.audits.append(
            _MemAudit(
                id=uuid4(),
                organization_id=organization_id,
                actor_user_id=actor_user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                result=result,
                request_id=request_id,
                metadata=metadata or {},
                created_at=datetime.now(UTC),
            )
        )

    async def list_audit(self, organization_id: UUID, limit: int = 50) -> list[AuditLog]:
        rows = [a for a in self.audits if a.organization_id == organization_id]
        rows.sort(key=lambda a: a.created_at, reverse=True)
        out: list[AuditLog] = []
        for row in rows[:limit]:
            log = AuditLog(
                id=row.id,
                organization_id=row.organization_id,
                actor_user_id=row.actor_user_id,
                action=row.action,
                resource_type=row.resource_type,
                resource_id=row.resource_id,
                result=row.result,
                request_id=row.request_id,
                metadata_=row.metadata,
                created_at=row.created_at,
            )
            out.append(log)
        return out
