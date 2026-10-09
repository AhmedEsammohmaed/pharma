from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.auth.principal import Membership, Principal
from app.auth.rbac import OrganizationRole, OrganizationType, Permission, has_permission
from app.core.errors import AppError
from app.modules.procurement.models import (
    InventoryBatch,
    InventoryMovement,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    SupplierInventoryBatch,
    SupplierProduct,
)
from app.modules.procurement.schemas import (
    OrderStatus,
    PurchaseOrderCreate,
    PurchaseOrderItemCreate,
    ReceivePurchaseOrderRequest,
    SupplierInventoryCreate,
    SupplierInventoryUpdate,
)
from app.modules.procurement.service import (
    ALLOWED_TRANSITIONS,
    money,
    require_org_access,
    require_transition,
    sellable_quantity,
)
from tests.conftest import auth_header


def test_order_transition_matrix_is_closed_and_controlled() -> None:
    assert ALLOWED_TRANSITIONS[OrderStatus.PENDING] == frozenset(
        {OrderStatus.CONFIRMED, OrderStatus.CANCELLED}
    )
    assert ALLOWED_TRANSITIONS[OrderStatus.SHIPPED] == frozenset(
        {OrderStatus.DELIVERED, OrderStatus.RETURNED}
    )
    assert ALLOWED_TRANSITIONS[OrderStatus.DELIVERED] == frozenset()
    require_transition(OrderStatus.PROCESSING, OrderStatus.READY)
    with pytest.raises(AppError) as exc:
        require_transition(OrderStatus.PENDING, OrderStatus.SHIPPED)
    assert exc.value.status_code == 409


def test_purchase_order_inputs_reject_bad_quantities_and_duplicate_batches() -> None:
    batch_id = uuid4()
    with pytest.raises(ValidationError):
        PurchaseOrderItemCreate(supplier_inventory_id=batch_id, quantity=0)
    with pytest.raises(ValidationError):
        PurchaseOrderCreate(
            supplier_id=uuid4(),
            items=[
                {"supplier_inventory_id": str(batch_id), "quantity": 5},
                {"supplier_inventory_id": str(batch_id), "quantity": 3},
            ],
        )


def test_supplier_inventory_inputs_reject_bad_price_quantity_and_expiry() -> None:
    base = {
        "product_id": str(uuid4()),
        "available_quantity": 15,
        "wholesale_price": "3.50",
        "minimum_order_quantity": 1,
    }
    with pytest.raises(ValidationError):
        SupplierInventoryCreate(**{**base, "available_quantity": 0})
    with pytest.raises(ValidationError):
        SupplierInventoryCreate(**{**base, "wholesale_price": "-1.00"})
    with pytest.raises(ValidationError):
        SupplierInventoryCreate(**{**base, "expiration_date": datetime.now(UTC).date() - timedelta(days=1)})
    with pytest.raises(ValidationError):
        SupplierInventoryUpdate(available_quantity=None)


def test_receipt_input_is_cumulative_and_rejects_duplicate_lines() -> None:
    line_id = uuid4()
    with pytest.raises(ValidationError):
        ReceivePurchaseOrderRequest(
            items=[
                {"item_id": str(line_id), "received_quantity": 2},
                {"item_id": str(line_id), "received_quantity": 2},
            ]
        )
    body = ReceivePurchaseOrderRequest(items=[{"item_id": str(line_id), "received_quantity": 2}])
    assert body.items[0].received_quantity == 2


def test_money_rounding_uses_decimal_arithmetic() -> None:
    assert money(Decimal("3.335") * 3) == Decimal("10.01")


def test_procurement_schema_models_include_persistent_ledger_entities() -> None:
    assert {
        "products",
        "supplier_products",
        "supplier_inventory_batches",
        "purchase_orders",
        "purchase_order_items",
        "inventory_batches",
        "inventory_movements",
    }.issubset(Product.metadata.tables)
    assert PurchaseOrderItem.__table__.c.received_quantity is not None
    assert InventoryMovement.__table__.c.quantity_delta is not None
    assert SupplierInventoryBatch.__table__.c.wholesale_price is not None
    assert SupplierInventoryBatch.__table__.c.reserved_quantity.server_default is not None
    assert SupplierProduct.__table__.c.supplier_id is not None
    assert PurchaseOrder.__table__.c.organization_id is not None
    assert InventoryBatch.__table__.c.purchase_order_item_id.unique


def test_supplier_sellable_quantity_excludes_active_reservations() -> None:
    batch = SupplierInventoryBatch(available_quantity=40, reserved_quantity=13)
    assert sellable_quantity(batch) == 27


def test_procurement_permissions_are_role_scoped() -> None:
    assert has_permission(OrganizationRole.PHARMACY_STAFF, Permission.PURCHASE_ORDERS_CREATE)
    assert has_permission(OrganizationRole.PHARMACY_STAFF, Permission.INVENTORY_RECEIVE)
    assert not has_permission(OrganizationRole.PHARMACY_STAFF, Permission.PURCHASE_ORDERS_MANAGE)
    assert has_permission(OrganizationRole.SUPPLIER_STAFF, Permission.SUPPLIER_INVENTORY_MANAGE)
    assert not has_permission(OrganizationRole.SUPPLIER_STAFF, Permission.INVENTORY_RECEIVE)


def test_cross_organization_access_returns_not_found_and_wrong_role_is_forbidden() -> None:
    pharmacy_id = uuid4()
    user = Principal(
        user_id=uuid4(),
        email="staff@example.com",
        full_name="Pharmacy Staff",
        phone=None,
        account_kind="staff",
        memberships=(
            Membership(
                organization_id=pharmacy_id,
                organization_name="Pharmacy A",
                organization_slug="pharmacy-a",
                organization_type=OrganizationType.PHARMACY,
                role=OrganizationRole.PHARMACY_STAFF,
                status="active",
            ),
        ),
    )
    with pytest.raises(AppError) as missing_org:
        require_org_access(user, uuid4(), OrganizationType.PHARMACY, Permission.PURCHASE_ORDERS_READ)
    assert missing_org.value.status_code == 404
    with pytest.raises(AppError) as forbidden:
        require_org_access(user, pharmacy_id, OrganizationType.PHARMACY, Permission.PURCHASE_ORDERS_MANAGE)
    assert forbidden.value.status_code == 403


def test_procurement_api_requires_auth_and_never_returns_demo_rows(client, user_a_id) -> None:
    headers = auth_header(str(user_a_id), "a@example.com")
    unauthenticated = client.get(
        "/api/v1/orders",
        headers={"X-Organization-Id": str(uuid4())},
    )
    assert unauthenticated.status_code == 401

    organization = client.post(
        "/api/v1/organizations",
        headers=headers,
        json={"name": "Order test pharmacy", "type": "pharmacy"},
    )
    assert organization.status_code == 201
    authorized_headers = {
        **headers,
        "X-Organization-Id": organization.json()["id"],
    }
    unavailable = client.get("/api/v1/orders", headers=authorized_headers)
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "database_unconfigured"
    assert "orders" not in unavailable.text
