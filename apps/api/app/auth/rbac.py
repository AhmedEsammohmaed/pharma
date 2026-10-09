from enum import StrEnum

from app.core.errors import AppError


class OrganizationType(StrEnum):
    PHARMACY = "pharmacy"
    SUPPLIER = "supplier"
    PLATFORM = "platform"


class OrganizationRole(StrEnum):
    PLATFORM_ADMIN = "platform_admin"
    PHARMACY_ADMIN = "pharmacy_admin"
    PHARMACY_STAFF = "pharmacy_staff"
    SUPPLIER_ADMIN = "supplier_admin"
    SUPPLIER_STAFF = "supplier_staff"


class Permission(StrEnum):
    ORG_READ = "org.read"
    ORG_UPDATE = "org.update"
    MEMBERS_READ = "members.read"
    MEMBERS_MANAGE = "members.manage"
    INVITES_CREATE = "invites.create"
    AUDIT_READ = "audit.read"
    PRODUCTS_READ = "products.read"
    SUPPLIER_INVENTORY_READ = "supplier_inventory.read"
    SUPPLIER_INVENTORY_MANAGE = "supplier_inventory.manage"
    PURCHASE_ORDERS_READ = "purchase_orders.read"
    PURCHASE_ORDERS_CREATE = "purchase_orders.create"
    PURCHASE_ORDERS_MANAGE = "purchase_orders.manage"
    PURCHASE_ORDERS_FULFILL = "purchase_orders.fulfill"
    INVENTORY_RECEIVE = "inventory.receive"


ROLE_PERMISSIONS: dict[OrganizationRole, frozenset[Permission]] = {
    OrganizationRole.PLATFORM_ADMIN: frozenset(Permission),
    OrganizationRole.PHARMACY_ADMIN: frozenset(
        {
            Permission.ORG_READ,
            Permission.ORG_UPDATE,
            Permission.MEMBERS_READ,
            Permission.MEMBERS_MANAGE,
            Permission.INVITES_CREATE,
            Permission.AUDIT_READ,
            Permission.PRODUCTS_READ,
            Permission.SUPPLIER_INVENTORY_READ,
            Permission.PURCHASE_ORDERS_READ,
            Permission.PURCHASE_ORDERS_CREATE,
            Permission.PURCHASE_ORDERS_MANAGE,
            Permission.INVENTORY_RECEIVE,
        }
    ),
    OrganizationRole.PHARMACY_STAFF: frozenset(
        {
            Permission.ORG_READ,
            Permission.MEMBERS_READ,
            Permission.PRODUCTS_READ,
            Permission.SUPPLIER_INVENTORY_READ,
            Permission.PURCHASE_ORDERS_READ,
            Permission.PURCHASE_ORDERS_CREATE,
            Permission.INVENTORY_RECEIVE,
        }
    ),
    OrganizationRole.SUPPLIER_ADMIN: frozenset(
        {
            Permission.ORG_READ,
            Permission.ORG_UPDATE,
            Permission.MEMBERS_READ,
            Permission.MEMBERS_MANAGE,
            Permission.INVITES_CREATE,
            Permission.AUDIT_READ,
            Permission.PRODUCTS_READ,
            Permission.SUPPLIER_INVENTORY_READ,
            Permission.SUPPLIER_INVENTORY_MANAGE,
            Permission.PURCHASE_ORDERS_READ,
            Permission.PURCHASE_ORDERS_FULFILL,
        }
    ),
    OrganizationRole.SUPPLIER_STAFF: frozenset(
        {
            Permission.ORG_READ,
            Permission.MEMBERS_READ,
            Permission.PRODUCTS_READ,
            Permission.SUPPLIER_INVENTORY_READ,
            Permission.SUPPLIER_INVENTORY_MANAGE,
            Permission.PURCHASE_ORDERS_READ,
            Permission.PURCHASE_ORDERS_FULFILL,
        }
    ),
}

ADMIN_ROLES = frozenset(
    {
        OrganizationRole.PLATFORM_ADMIN,
        OrganizationRole.PHARMACY_ADMIN,
        OrganizationRole.SUPPLIER_ADMIN,
    }
)

_ROLE_ORG_TYPES: dict[OrganizationRole, frozenset[OrganizationType]] = {
    OrganizationRole.PLATFORM_ADMIN: frozenset({OrganizationType.PLATFORM}),
    OrganizationRole.PHARMACY_ADMIN: frozenset({OrganizationType.PHARMACY}),
    OrganizationRole.PHARMACY_STAFF: frozenset({OrganizationType.PHARMACY}),
    OrganizationRole.SUPPLIER_ADMIN: frozenset({OrganizationType.SUPPLIER}),
    OrganizationRole.SUPPLIER_STAFF: frozenset({OrganizationType.SUPPLIER}),
}

_CREATE_ORG_ADMIN_ROLE: dict[OrganizationType, OrganizationRole] = {
    OrganizationType.PHARMACY: OrganizationRole.PHARMACY_ADMIN,
    OrganizationType.SUPPLIER: OrganizationRole.SUPPLIER_ADMIN,
    OrganizationType.PLATFORM: OrganizationRole.PLATFORM_ADMIN,
}


def permissions_for(role: OrganizationRole) -> frozenset[Permission]:
    return ROLE_PERMISSIONS[role]


def has_permission(role: OrganizationRole, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS[role]


def require_permission(role: OrganizationRole, permission: Permission) -> None:
    if not has_permission(role, permission):
        raise AppError(403, "forbidden", "You do not have permission to perform this action")


def role_matches_org_type(role: OrganizationRole, org_type: OrganizationType) -> bool:
    return org_type in _ROLE_ORG_TYPES[role]


def require_role_matches_org_type(role: OrganizationRole, org_type: OrganizationType) -> None:
    if not role_matches_org_type(role, org_type):
        raise AppError(422, "role_org_mismatch", "Role is not valid for this organization type")


def admin_role_for_org_type(org_type: OrganizationType) -> OrganizationRole:
    return _CREATE_ORG_ADMIN_ROLE[org_type]
