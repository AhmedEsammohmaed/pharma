from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Membership, Principal
from app.auth.rbac import OrganizationType, Permission, has_permission
from app.core.errors import AppError
from app.modules.identity.models import AuditLog, Organization
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
    InventoryBatchOut,
    InventoryMovementOut,
    OrderStatus,
    ProductOut,
    PurchaseOrderCreate,
    PurchaseOrderItemOut,
    PurchaseOrderOut,
    PurchaseOrderUpdate,
    ReceivePurchaseOrderRequest,
    SupplierInventoryCreate,
    SupplierInventoryOut,
    SupplierInventoryStatus,
    SupplierInventoryUpdate,
    SupplierOut,
)

ALLOWED_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.PENDING: frozenset({OrderStatus.CONFIRMED, OrderStatus.CANCELLED}),
    OrderStatus.CONFIRMED: frozenset({OrderStatus.PROCESSING, OrderStatus.CANCELLED}),
    OrderStatus.PROCESSING: frozenset({OrderStatus.READY, OrderStatus.CANCELLED}),
    OrderStatus.READY: frozenset({OrderStatus.SHIPPED, OrderStatus.CANCELLED}),
    OrderStatus.SHIPPED: frozenset({OrderStatus.DELIVERED, OrderStatus.RETURNED}),
    OrderStatus.DELIVERED: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
    OrderStatus.RETURNED: frozenset(),
}

_CENTS = Decimal("0.01")


def _utc_today() -> date:
    return datetime.now(UTC).date()


def money(value: Decimal) -> Decimal:
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


def sellable_quantity(batch: SupplierInventoryBatch) -> int:
    return batch.available_quantity - batch.reserved_quantity


def require_org_access(
    principal: Principal,
    organization_id: UUID,
    organization_type: OrganizationType,
    permission: Permission,
) -> Membership:
    membership = principal.require_org_permission(organization_id, permission)
    if membership.organization_type != organization_type:
        raise AppError(403, "forbidden", "This action is not available for this organization type")
    return membership


def require_transition(current: OrderStatus, target: OrderStatus) -> None:
    if target not in ALLOWED_TRANSITIONS[current]:
        raise AppError(409, "invalid_order_transition", f"An order cannot move from {current.value} to {target.value}")


def _audit(
    session: AsyncSession,
    *,
    actor_id: UUID,
    organization_id: UUID,
    action: str,
    resource_type: str,
    resource_id: UUID | str,
    request_id: str | None,
    metadata: dict | None = None,
) -> None:
    session.add(
        AuditLog(
            actor_user_id=actor_id,
            organization_id=organization_id,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id),
            result="success",
            request_id=request_id,
            metadata_=metadata or {},
        )
    )


async def list_products(session: AsyncSession, principal: Principal, organization_id: UUID) -> list[ProductOut]:
    require_membership = principal.membership(organization_id)
    if require_membership.organization_type not in {OrganizationType.PHARMACY, OrganizationType.SUPPLIER}:
        raise AppError(403, "forbidden", "Product catalog is not available to this organization")
    if not has_permission(require_membership.role, Permission.PRODUCTS_READ):
        raise AppError(403, "forbidden", "You do not have permission to view products")
    rows = (
        await session.execute(select(Product).where(Product.active.is_(True)).order_by(Product.name).limit(500))
    ).scalars()
    return [
        ProductOut(
            id=row.id,
            sku=row.sku,
            name=row.name,
            generic_name=row.generic_name,
            strength=row.strength,
            dosage_form=row.dosage_form,
            unit=row.unit,
            category=row.category,
        )
        for row in rows
    ]


async def list_suppliers(
    session: AsyncSession, principal: Principal, organization_id: UUID
) -> list[SupplierOut]:
    membership = principal.membership(organization_id)
    if membership.organization_type == OrganizationType.PHARMACY:
        principal.require_org_permission(organization_id, Permission.SUPPLIER_INVENTORY_READ)
        scope = Organization.id != organization_id
    elif membership.organization_type == OrganizationType.SUPPLIER:
        principal.require_org_permission(organization_id, Permission.SUPPLIER_INVENTORY_READ)
        scope = Organization.id == organization_id
    else:
        raise AppError(403, "forbidden", "Supplier catalog is not available to this organization")

    statement = (
        select(
            Organization.id,
            Organization.name,
            Organization.slug,
            func.min(SupplierProduct.lead_time_days),
            func.count(func.distinct(SupplierProduct.product_id)),
        )
        .join(SupplierProduct, SupplierProduct.supplier_id == Organization.id)
        .join(SupplierInventoryBatch, SupplierInventoryBatch.supplier_product_id == SupplierProduct.id)
        .where(
            Organization.type == OrganizationType.SUPPLIER.value,
            Organization.status == "active",
            Organization.deleted_at.is_(None),
            SupplierProduct.active.is_(True),
            SupplierInventoryBatch.status == SupplierInventoryStatus.AVAILABLE.value,
            SupplierInventoryBatch.deleted_at.is_(None),
            SupplierInventoryBatch.available_quantity > SupplierInventoryBatch.reserved_quantity,
            or_(SupplierInventoryBatch.expiration_date.is_(None), SupplierInventoryBatch.expiration_date > _utc_today()),
            scope,
        )
        .group_by(Organization.id, Organization.name, Organization.slug)
        .order_by(Organization.name)
    )
    return [
        SupplierOut(id=row[0], name=row[1], slug=row[2], lead_time_days=row[3] or 0, listed_products=row[4])
        for row in (await session.execute(statement)).all()
    ]


async def _supplier_inventory_out(session: AsyncSession, batch: SupplierInventoryBatch) -> SupplierInventoryOut:
    statement = (
        select(SupplierProduct, Product, Organization)
        .join(Product, Product.id == SupplierProduct.product_id)
        .join(Organization, Organization.id == SupplierProduct.supplier_id)
        .where(SupplierProduct.id == batch.supplier_product_id)
    )
    row = (await session.execute(statement)).one()
    supplier_product, product, supplier = row
    return SupplierInventoryOut(
        id=batch.id,
        supplier_id=batch.supplier_id,
        supplier_name=supplier.name,
        supplier_product_id=supplier_product.id,
        product_id=product.id,
        product_name=product.name,
        product_sku=product.sku,
        unit=product.unit,
        supplier_sku=supplier_product.supplier_sku,
        batch_number=batch.batch_number,
        available_quantity=sellable_quantity(batch),
        wholesale_price=batch.wholesale_price,
        minimum_order_quantity=batch.minimum_order_quantity,
        lead_time_days=supplier_product.lead_time_days,
        expiration_date=batch.expiration_date,
        status=SupplierInventoryStatus(batch.status),
        updated_at=batch.updated_at,
    )


async def list_supplier_inventory(
    session: AsyncSession,
    principal: Principal,
    organization_id: UUID,
    supplier_id: UUID,
) -> list[SupplierInventoryOut]:
    membership = principal.membership(organization_id)
    principal.require_org_permission(organization_id, Permission.SUPPLIER_INVENTORY_READ)
    if membership.organization_type == OrganizationType.SUPPLIER and organization_id != supplier_id:
        raise AppError(404, "not_found", "Supplier not found")
    if membership.organization_type not in {OrganizationType.PHARMACY, OrganizationType.SUPPLIER}:
        raise AppError(403, "forbidden", "Supplier inventory is not available to this organization")
    supplier = await session.get(Organization, supplier_id)
    if (
        supplier is None
        or supplier.type != OrganizationType.SUPPLIER.value
        or supplier.status != "active"
        or supplier.deleted_at is not None
    ):
        raise AppError(404, "not_found", "Supplier not found")
    statement = (
        select(SupplierInventoryBatch)
        .join(SupplierProduct, SupplierProduct.id == SupplierInventoryBatch.supplier_product_id)
        .where(
            SupplierInventoryBatch.supplier_id == supplier_id,
            SupplierInventoryBatch.deleted_at.is_(None),
            SupplierProduct.active.is_(True),
        )
        .order_by(SupplierInventoryBatch.updated_at.desc())
    )
    if membership.organization_type == OrganizationType.PHARMACY:
        statement = statement.where(
            SupplierInventoryBatch.status == SupplierInventoryStatus.AVAILABLE.value,
            SupplierInventoryBatch.available_quantity > SupplierInventoryBatch.reserved_quantity,
            or_(SupplierInventoryBatch.expiration_date.is_(None), SupplierInventoryBatch.expiration_date > _utc_today()),
        )
    batches = (await session.execute(statement)).scalars().all()
    return [await _supplier_inventory_out(session, batch) for batch in batches]


async def create_supplier_inventory(
    session: AsyncSession,
    principal: Principal,
    organization_id: UUID,
    payload: SupplierInventoryCreate,
    request_id: str | None,
) -> SupplierInventoryOut:
    require_org_access(
        principal,
        organization_id,
        OrganizationType.SUPPLIER,
        Permission.SUPPLIER_INVENTORY_MANAGE,
    )
    # Lock the supplier row to serialize creation of a product listing and its first batch.
    supplier = (
        await session.execute(
            select(Organization)
            .where(Organization.id == organization_id, Organization.type == OrganizationType.SUPPLIER.value)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if supplier is None or supplier.status != "active" or supplier.deleted_at is not None:
        raise AppError(404, "not_found", "Supplier not found")
    product = await session.get(Product, payload.product_id)
    if product is None or not product.active:
        raise AppError(404, "product_not_found", "Product not found")

    supplier_product = (
        await session.execute(
            select(SupplierProduct)
            .where(SupplierProduct.supplier_id == organization_id, SupplierProduct.product_id == product.id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    supplier_product_created = supplier_product is None
    if supplier_product is None:
        supplier_product = SupplierProduct(
            supplier_id=organization_id,
            product_id=product.id,
            supplier_sku=payload.supplier_sku,
            lead_time_days=payload.lead_time_days,
            active=True,
            created_by=principal.user_id,
        )
        session.add(supplier_product)
        await session.flush()
    else:
        supplier_product.active = True
        supplier_product.supplier_sku = payload.supplier_sku or supplier_product.supplier_sku
        supplier_product.lead_time_days = payload.lead_time_days

    batch_query = select(SupplierInventoryBatch).where(
        SupplierInventoryBatch.supplier_product_id == supplier_product.id,
        SupplierInventoryBatch.batch_number.is_(None)
        if payload.batch_number is None
        else SupplierInventoryBatch.batch_number == payload.batch_number,
    ).with_for_update()
    batch = (await session.execute(batch_query)).scalar_one_or_none()
    if batch is not None and batch.deleted_at is None:
        raise AppError(409, "inventory_batch_exists", "This supplier batch already exists; update it instead")
    if batch is None:
        batch = SupplierInventoryBatch(
            supplier_product_id=supplier_product.id,
            supplier_id=organization_id,
            product_id=product.id,
            batch_number=payload.batch_number,
            available_quantity=payload.available_quantity,
            wholesale_price=payload.wholesale_price,
            minimum_order_quantity=payload.minimum_order_quantity,
            expiration_date=payload.expiration_date,
            status=SupplierInventoryStatus.AVAILABLE.value,
        )
        session.add(batch)
    else:
        batch.available_quantity = payload.available_quantity
        batch.wholesale_price = payload.wholesale_price
        batch.minimum_order_quantity = payload.minimum_order_quantity
        batch.expiration_date = payload.expiration_date
        batch.status = SupplierInventoryStatus.AVAILABLE.value
        batch.deleted_at = None
    await session.flush()
    if supplier_product_created:
        _audit(
            session,
            actor_id=principal.user_id,
            organization_id=organization_id,
            action="supplier_product.created",
            resource_type="supplier_product",
            resource_id=supplier_product.id,
            request_id=request_id,
            metadata={"product_id": str(product.id)},
        )
    _audit(
        session,
        actor_id=principal.user_id,
        organization_id=organization_id,
        action="supplier_inventory.created",
        resource_type="supplier_inventory_batch",
        resource_id=batch.id,
        request_id=request_id,
        metadata={"product_id": str(product.id), "available_quantity": batch.available_quantity},
    )
    await session.flush()
    return await _supplier_inventory_out(session, batch)


async def update_supplier_inventory(
    session: AsyncSession,
    principal: Principal,
    organization_id: UUID,
    inventory_id: UUID,
    payload: SupplierInventoryUpdate,
    request_id: str | None,
) -> SupplierInventoryOut:
    require_org_access(
        principal,
        organization_id,
        OrganizationType.SUPPLIER,
        Permission.SUPPLIER_INVENTORY_MANAGE,
    )
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise AppError(422, "empty_update", "Provide at least one inventory field to update")
    batch = (
        await session.execute(
            select(SupplierInventoryBatch)
            .where(
                SupplierInventoryBatch.id == inventory_id,
                SupplierInventoryBatch.supplier_id == organization_id,
                SupplierInventoryBatch.deleted_at.is_(None),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if batch is None:
        raise AppError(404, "not_found", "Supplier inventory item not found")
    changed_fields = sorted(changes)
    supplier_changes = {key: changes.pop(key) for key in ("supplier_sku", "lead_time_days") if key in changes}
    if supplier_changes:
        supplier_product = await session.get(SupplierProduct, batch.supplier_product_id)
        if supplier_product is None:
            raise AppError(404, "not_found", "Supplier product not found")
        for field, value in supplier_changes.items():
            setattr(supplier_product, field, value)
    if "available_quantity" in changes:
        requested_available_quantity = changes.pop("available_quantity")
        if requested_available_quantity is not None:
            batch.available_quantity = batch.reserved_quantity + requested_available_quantity
    for field, value in changes.items():
        if field == "status" and value is not None:
            value = value.value
        setattr(batch, field, value)
    if sellable_quantity(batch) == 0:
        batch.status = SupplierInventoryStatus.UNAVAILABLE.value
    elif "available_quantity" in payload.model_fields_set and batch.status == SupplierInventoryStatus.UNAVAILABLE.value:
        batch.status = SupplierInventoryStatus.AVAILABLE.value
    await session.flush()
    _audit(
        session,
        actor_id=principal.user_id,
        organization_id=organization_id,
        action="supplier_inventory.updated",
        resource_type="supplier_inventory_batch",
        resource_id=batch.id,
        request_id=request_id,
        metadata={"changed_fields": changed_fields},
    )
    await session.flush()
    return await _supplier_inventory_out(session, batch)


async def delete_supplier_inventory(
    session: AsyncSession,
    principal: Principal,
    organization_id: UUID,
    inventory_id: UUID,
    request_id: str | None,
) -> None:
    require_org_access(
        principal,
        organization_id,
        OrganizationType.SUPPLIER,
        Permission.SUPPLIER_INVENTORY_MANAGE,
    )
    batch = (
        await session.execute(
            select(SupplierInventoryBatch)
            .where(
                SupplierInventoryBatch.id == inventory_id,
                SupplierInventoryBatch.supplier_id == organization_id,
                SupplierInventoryBatch.deleted_at.is_(None),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if batch is None:
        raise AppError(404, "not_found", "Supplier inventory item not found")
    if batch.reserved_quantity:
        raise AppError(409, "inventory_reserved", "This batch has quantities committed to active orders")
    batch.deleted_at = datetime.now(UTC)
    batch.status = SupplierInventoryStatus.UNAVAILABLE.value
    other_available = (
        await session.execute(
            select(func.count())
            .select_from(SupplierInventoryBatch)
            .where(
                SupplierInventoryBatch.supplier_product_id == batch.supplier_product_id,
                SupplierInventoryBatch.id != batch.id,
                SupplierInventoryBatch.deleted_at.is_(None),
                SupplierInventoryBatch.status == SupplierInventoryStatus.AVAILABLE.value,
                SupplierInventoryBatch.available_quantity > SupplierInventoryBatch.reserved_quantity,
            )
        )
    ).scalar_one()
    if not other_available:
        supplier_product = await session.get(SupplierProduct, batch.supplier_product_id)
        if supplier_product is not None:
            supplier_product.active = False
    await session.flush()
    _audit(
        session,
        actor_id=principal.user_id,
        organization_id=organization_id,
        action="supplier_inventory.deleted",
        resource_type="supplier_inventory_batch",
        resource_id=batch.id,
        request_id=request_id,
        metadata={"product_id": str(batch.product_id)},
    )
    await session.flush()


async def _order_for_org(
    session: AsyncSession, order_id: UUID, organization_id: UUID, lock: bool = False
) -> PurchaseOrder:
    statement = select(PurchaseOrder).where(
        PurchaseOrder.id == order_id,
        or_(PurchaseOrder.organization_id == organization_id, PurchaseOrder.supplier_id == organization_id),
    )
    if lock:
        statement = statement.with_for_update()
    order = (await session.execute(statement)).scalar_one_or_none()
    if order is None:
        raise AppError(404, "not_found", "Purchase order not found")
    return order


async def _order_items(session: AsyncSession, order: PurchaseOrder, lock: bool = False) -> list[PurchaseOrderItem]:
    statement = select(PurchaseOrderItem).where(PurchaseOrderItem.purchase_order_id == order.id).order_by(
        PurchaseOrderItem.created_at, PurchaseOrderItem.id
    )
    if lock:
        statement = statement.with_for_update()
    return list((await session.execute(statement)).scalars().all())


async def serialize_order(session: AsyncSession, order: PurchaseOrder) -> PurchaseOrderOut:
    supplier = await session.get(Organization, order.supplier_id)
    if supplier is None:
        raise AppError(404, "not_found", "Supplier not found")
    line_rows = (
        await session.execute(
            select(PurchaseOrderItem, Product, SupplierInventoryBatch)
            .join(Product, Product.id == PurchaseOrderItem.product_id)
            .join(SupplierInventoryBatch, SupplierInventoryBatch.id == PurchaseOrderItem.supplier_inventory_id)
            .where(PurchaseOrderItem.purchase_order_id == order.id)
            .order_by(PurchaseOrderItem.created_at, PurchaseOrderItem.id)
        )
    ).all()
    return PurchaseOrderOut(
        id=order.id,
        organization_id=order.organization_id,
        supplier_id=order.supplier_id,
        supplier_name=supplier.name,
        order_number=order.order_number,
        status=OrderStatus(order.status),
        subtotal=order.subtotal,
        tax_total=order.tax_total,
        total=order.total,
        notes=order.notes,
        created_at=order.created_at,
        updated_at=order.updated_at,
        items=[
            PurchaseOrderItemOut(
                id=item.id,
                product_id=product.id,
                product_name=product.name,
                product_sku=product.sku,
                supplier_inventory_id=batch.id,
                batch_number=batch.batch_number,
                quantity=item.quantity,
                received_quantity=item.received_quantity,
                unit_price=item.unit_price,
                line_total=item.line_total,
            )
            for item, product, batch in line_rows
        ],
    )


async def list_purchase_orders(
    session: AsyncSession, principal: Principal, organization_id: UUID
) -> list[PurchaseOrderOut]:
    membership = principal.membership(organization_id)
    principal.require_org_permission(organization_id, Permission.PURCHASE_ORDERS_READ)
    if membership.organization_type == OrganizationType.PHARMACY:
        statement = select(PurchaseOrder).where(PurchaseOrder.organization_id == organization_id)
    elif membership.organization_type == OrganizationType.SUPPLIER:
        statement = select(PurchaseOrder).where(PurchaseOrder.supplier_id == organization_id)
    else:
        raise AppError(403, "forbidden", "Purchase orders are not available to this organization")
    orders = (await session.execute(statement.order_by(PurchaseOrder.created_at.desc()).limit(200))).scalars().all()
    return [await serialize_order(session, order) for order in orders]


async def get_purchase_order(
    session: AsyncSession, principal: Principal, organization_id: UUID, order_id: UUID
) -> PurchaseOrderOut:
    membership = principal.membership(organization_id)
    principal.require_org_permission(organization_id, Permission.PURCHASE_ORDERS_READ)
    if membership.organization_type not in {OrganizationType.PHARMACY, OrganizationType.SUPPLIER}:
        raise AppError(403, "forbidden", "Purchase orders are not available to this organization")
    order = await _order_for_org(session, order_id, organization_id)
    return await serialize_order(session, order)


async def create_purchase_order(
    session: AsyncSession,
    principal: Principal,
    organization_id: UUID,
    payload: PurchaseOrderCreate,
    request_id: str | None,
) -> PurchaseOrderOut:
    require_org_access(principal, organization_id, OrganizationType.PHARMACY, Permission.PURCHASE_ORDERS_CREATE)
    supplier = await session.get(Organization, payload.supplier_id)
    if (
        supplier is None
        or supplier.type != OrganizationType.SUPPLIER.value
        or supplier.status != "active"
        or supplier.deleted_at is not None
    ):
        raise AppError(404, "supplier_not_found", "Supplier not found")

    requested = {item.supplier_inventory_id: item.quantity for item in payload.items}
    batch_rows = (
        await session.execute(
            select(SupplierInventoryBatch, SupplierProduct, Product)
            .join(SupplierProduct, SupplierProduct.id == SupplierInventoryBatch.supplier_product_id)
            .join(Product, Product.id == SupplierInventoryBatch.product_id)
            .where(
                SupplierInventoryBatch.id.in_(requested),
                SupplierInventoryBatch.supplier_id == payload.supplier_id,
                SupplierInventoryBatch.deleted_at.is_(None),
                SupplierInventoryBatch.status == SupplierInventoryStatus.AVAILABLE.value,
                SupplierProduct.active.is_(True),
                Product.active.is_(True),
                or_(SupplierInventoryBatch.expiration_date.is_(None), SupplierInventoryBatch.expiration_date > _utc_today()),
            )
            .order_by(SupplierInventoryBatch.id)
            .with_for_update(of=SupplierInventoryBatch)
        )
    ).all()
    if len(batch_rows) != len(requested):
        raise AppError(404, "inventory_not_found", "One or more selected supplier batches are unavailable")
    subtotal = Decimal("0.00")
    for batch, _supplier_product, _product in batch_rows:
        quantity = requested[batch.id]
        if quantity < batch.minimum_order_quantity:
            raise AppError(
                422,
                "below_minimum_order_quantity",
                f"Order quantity for a selected product must be at least {batch.minimum_order_quantity}",
            )
        if quantity > sellable_quantity(batch):
            raise AppError(409, "insufficient_supplier_inventory", "A selected supplier batch no longer has enough stock")
        subtotal += money(batch.wholesale_price * quantity)
    subtotal = money(subtotal)
    now = datetime.now(UTC)
    order = PurchaseOrder(
        organization_id=organization_id,
        supplier_id=payload.supplier_id,
        order_number=f"PO-{now:%y%m%d}-{uuid4().hex[:8].upper()}",
        status=OrderStatus.PENDING.value,
        subtotal=subtotal,
        tax_total=Decimal("0.00"),
        total=subtotal,
        notes=payload.notes,
        created_by=principal.user_id,
    )
    session.add(order)
    await session.flush()
    for batch, _supplier_product, _product in batch_rows:
        quantity = requested[batch.id]
        unit_price = money(batch.wholesale_price)
        session.add(
            PurchaseOrderItem(
                purchase_order_id=order.id,
                organization_id=organization_id,
                supplier_id=payload.supplier_id,
                supplier_inventory_id=batch.id,
                product_id=batch.product_id,
                quantity=quantity,
                received_quantity=0,
                unit_price=unit_price,
                line_total=money(unit_price * quantity),
            )
        )
    await session.flush()
    _audit(
        session,
        actor_id=principal.user_id,
        organization_id=organization_id,
        action="purchase_order.created",
        resource_type="purchase_order",
        resource_id=order.id,
        request_id=request_id,
        metadata={"supplier_id": str(payload.supplier_id), "item_count": len(batch_rows), "total": str(order.total)},
    )
    await session.flush()
    return await serialize_order(session, order)


async def update_purchase_order(
    session: AsyncSession,
    principal: Principal,
    organization_id: UUID,
    order_id: UUID,
    payload: PurchaseOrderUpdate,
    request_id: str | None,
) -> PurchaseOrderOut:
    require_org_access(principal, organization_id, OrganizationType.PHARMACY, Permission.PURCHASE_ORDERS_MANAGE)
    order = await _order_for_org(session, order_id, organization_id, lock=True)
    if order.organization_id != organization_id:
        raise AppError(404, "not_found", "Purchase order not found")
    if order.status != OrderStatus.PENDING.value:
        raise AppError(409, "order_not_editable", "Only pending purchase orders can be edited")
    order.notes = payload.notes
    await session.flush()
    _audit(
        session,
        actor_id=principal.user_id,
        organization_id=organization_id,
        action="purchase_order.updated",
        resource_type="purchase_order",
        resource_id=order.id,
        request_id=request_id,
        metadata={"changed_fields": ["notes"]},
    )
    await session.flush()
    return await serialize_order(session, order)


async def transition_purchase_order(
    session: AsyncSession,
    principal: Principal,
    organization_id: UUID,
    order_id: UUID,
    target_status: OrderStatus,
    request_id: str | None,
) -> PurchaseOrderOut:
    membership = principal.membership(organization_id)
    if membership.organization_type not in {OrganizationType.PHARMACY, OrganizationType.SUPPLIER}:
        raise AppError(403, "forbidden", "Purchase order actions are not available to this organization")
    order = await _order_for_org(session, order_id, organization_id, lock=True)
    require_transition(OrderStatus(order.status), target_status)
    if target_status == OrderStatus.DELIVERED:
        raise AppError(409, "receive_required", "Use the receive endpoint to complete delivery into pharmacy inventory")

    if target_status in {OrderStatus.CONFIRMED, OrderStatus.PROCESSING, OrderStatus.READY, OrderStatus.SHIPPED, OrderStatus.RETURNED}:
        require_org_access(
            principal,
            organization_id,
            OrganizationType.SUPPLIER,
            Permission.PURCHASE_ORDERS_FULFILL,
        )
        if order.supplier_id != organization_id:
            raise AppError(404, "not_found", "Purchase order not found")
    elif target_status == OrderStatus.CANCELLED:
        if membership.organization_type == OrganizationType.PHARMACY:
            require_org_access(principal, organization_id, OrganizationType.PHARMACY, Permission.PURCHASE_ORDERS_MANAGE)
            if order.organization_id != organization_id:
                raise AppError(404, "not_found", "Purchase order not found")
        else:
            principal.require_org_permission(organization_id, Permission.PURCHASE_ORDERS_FULFILL)
            if order.supplier_id != organization_id:
                raise AppError(404, "not_found", "Purchase order not found")

    if target_status == OrderStatus.CONFIRMED:
        items = await _order_items(session, order, lock=True)
        batch_ids = [item.supplier_inventory_id for item in items]
        batches = (
            await session.execute(
                select(SupplierInventoryBatch)
                .where(SupplierInventoryBatch.id.in_(batch_ids))
                .order_by(SupplierInventoryBatch.id)
                .with_for_update()
            )
        ).scalars().all()
        by_id = {batch.id: batch for batch in batches}
        for item in items:
            batch = by_id.get(item.supplier_inventory_id)
            if (
                batch is None
                or batch.status != SupplierInventoryStatus.AVAILABLE.value
                or batch.deleted_at is not None
                or sellable_quantity(batch) < item.quantity
            ):
                raise AppError(409, "insufficient_supplier_inventory", "Supplier stock changed before confirmation")
            if batch.expiration_date is not None and batch.expiration_date <= _utc_today():
                raise AppError(409, "supplier_batch_expired", "An order item is no longer available because its batch expired")
        for item in items:
            batch = by_id[item.supplier_inventory_id]
            batch.reserved_quantity += item.quantity
            if sellable_quantity(batch) == 0:
                batch.status = SupplierInventoryStatus.UNAVAILABLE.value
            _audit(
                session,
                actor_id=principal.user_id,
                organization_id=organization_id,
                action="supplier_inventory.reserved",
                resource_type="supplier_inventory_batch",
                resource_id=batch.id,
                request_id=request_id,
                metadata={"purchase_order_id": str(order.id), "quantity": item.quantity},
            )

    if target_status == OrderStatus.SHIPPED:
        items = await _order_items(session, order, lock=True)
        batch_ids = [item.supplier_inventory_id for item in items]
        batches = (
            await session.execute(
                select(SupplierInventoryBatch)
                .where(SupplierInventoryBatch.id.in_(batch_ids))
                .order_by(SupplierInventoryBatch.id)
                .with_for_update()
            )
        ).scalars().all()
        by_id = {batch.id: batch for batch in batches}
        for item in items:
            batch = by_id.get(item.supplier_inventory_id)
            if (
                batch is None
                or batch.available_quantity < item.quantity
                or batch.reserved_quantity < item.quantity
            ):
                raise AppError(409, "insufficient_supplier_inventory", "Supplier stock is insufficient to ship this order")
            batch.available_quantity -= item.quantity
            batch.reserved_quantity -= item.quantity
            if sellable_quantity(batch) == 0:
                batch.status = SupplierInventoryStatus.UNAVAILABLE.value
            elif batch.deleted_at is None:
                batch.status = SupplierInventoryStatus.AVAILABLE.value

    if target_status == OrderStatus.CANCELLED and order.status in {
        OrderStatus.CONFIRMED.value,
        OrderStatus.PROCESSING.value,
        OrderStatus.READY.value,
    }:
        items = await _order_items(session, order, lock=True)
        batch_ids = [item.supplier_inventory_id for item in items]
        batches = (
            await session.execute(
                select(SupplierInventoryBatch)
                .where(SupplierInventoryBatch.id.in_(batch_ids))
                .order_by(SupplierInventoryBatch.id)
                .with_for_update()
            )
        ).scalars().all()
        by_id = {batch.id: batch for batch in batches}
        for item in items:
            batch = by_id.get(item.supplier_inventory_id)
            if batch is None or batch.reserved_quantity < item.quantity:
                raise AppError(409, "reservation_missing", "The active supplier stock reservation could not be released")
        for item in items:
            batch = by_id[item.supplier_inventory_id]
            batch.reserved_quantity -= item.quantity
            if sellable_quantity(batch) > 0 and batch.deleted_at is None:
                batch.status = SupplierInventoryStatus.AVAILABLE.value
            _audit(
                session,
                actor_id=principal.user_id,
                organization_id=organization_id,
                action="supplier_inventory.reservation_released",
                resource_type="supplier_inventory_batch",
                resource_id=batch.id,
                request_id=request_id,
                metadata={"purchase_order_id": str(order.id), "quantity": item.quantity},
            )

    if target_status == OrderStatus.RETURNED:
        items = await _order_items(session, order, lock=True)
        if any(item.received_quantity for item in items):
            raise AppError(409, "order_already_received", "Received goods require a separate pharmacy return workflow")
        batch_ids = [item.supplier_inventory_id for item in items]
        batches = (
            await session.execute(
                select(SupplierInventoryBatch)
                .where(SupplierInventoryBatch.id.in_(batch_ids))
                .order_by(SupplierInventoryBatch.id)
                .with_for_update()
            )
        ).scalars().all()
        by_id = {batch.id: batch for batch in batches}
        for item in items:
            batch = by_id.get(item.supplier_inventory_id)
            if batch is not None:
                batch.available_quantity += item.quantity
                if batch.deleted_at is None:
                    batch.status = SupplierInventoryStatus.AVAILABLE.value

    previous = order.status
    order.status = target_status.value
    await session.flush()
    _audit(
        session,
        actor_id=principal.user_id,
        organization_id=organization_id,
        action=(
            "purchase_order.cancelled"
            if target_status == OrderStatus.CANCELLED
            else "purchase_order.confirmed"
            if target_status == OrderStatus.CONFIRMED
            else "purchase_order.status_changed"
        ),
        resource_type="purchase_order",
        resource_id=order.id,
        request_id=request_id,
        metadata={"from": previous, "to": target_status.value},
    )
    if target_status == OrderStatus.SHIPPED:
        for item in await _order_items(session, order):
            _audit(
                session,
                actor_id=principal.user_id,
                organization_id=organization_id,
                action="supplier_inventory.shipped",
                resource_type="supplier_inventory_batch",
                resource_id=item.supplier_inventory_id,
                request_id=request_id,
                metadata={"purchase_order_id": str(order.id), "quantity_delta": -item.quantity},
            )
    elif target_status == OrderStatus.RETURNED:
        for item in await _order_items(session, order):
            _audit(
                session,
                actor_id=principal.user_id,
                organization_id=organization_id,
                action="supplier_inventory.returned",
                resource_type="supplier_inventory_batch",
                resource_id=item.supplier_inventory_id,
                request_id=request_id,
                metadata={"purchase_order_id": str(order.id), "quantity_delta": item.quantity},
            )
    await session.flush()
    return await serialize_order(session, order)


async def receive_purchase_order(
    session: AsyncSession,
    principal: Principal,
    organization_id: UUID,
    order_id: UUID,
    payload: ReceivePurchaseOrderRequest,
    request_id: str | None,
) -> PurchaseOrderOut:
    require_org_access(principal, organization_id, OrganizationType.PHARMACY, Permission.INVENTORY_RECEIVE)
    order = await _order_for_org(session, order_id, organization_id, lock=True)
    if order.organization_id != organization_id:
        raise AppError(404, "not_found", "Purchase order not found")
    if order.status not in {OrderStatus.SHIPPED.value, OrderStatus.DELIVERED.value}:
        raise AppError(409, "order_not_receivable", "Only shipped purchase orders can be received")
    items = await _order_items(session, order, lock=True)
    requested = {item.item_id: item.received_quantity for item in payload.items}
    if set(requested) != {item.id for item in items}:
        raise AppError(422, "receive_items_mismatch", "Include each purchase order line exactly once")

    changed = False
    for item in items:
        target = requested[item.id]
        if target < item.received_quantity:
            raise AppError(409, "received_quantity_cannot_decrease", "Received quantities cannot be reduced")
        if target > item.quantity:
            raise AppError(422, "received_quantity_exceeds_order", "Received quantity cannot exceed the ordered quantity")
        delta = target - item.received_quantity
        if delta == 0:
            continue
        changed = True
        item.received_quantity = target
        batch = (
            await session.execute(
                select(InventoryBatch)
                .where(InventoryBatch.purchase_order_item_id == item.id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if batch is None:
            source = await session.get(SupplierInventoryBatch, item.supplier_inventory_id)
            if source is None:
                raise AppError(409, "supplier_batch_missing", "The source batch for this order item is no longer available")
            batch = InventoryBatch(
                organization_id=organization_id,
                product_id=item.product_id,
                supplier_id=order.supplier_id,
                purchase_order_item_id=item.id,
                batch_number=source.batch_number,
                expiration_date=source.expiration_date,
                quantity_on_hand=delta,
                unit_cost=item.unit_price,
            )
            session.add(batch)
            await session.flush()
        else:
            batch.quantity_on_hand += delta
        session.add(
            InventoryMovement(
                organization_id=organization_id,
                product_id=item.product_id,
                inventory_batch_id=batch.id,
                purchase_order_item_id=item.id,
                movement_type="receipt",
                quantity_delta=delta,
                unit_cost=item.unit_price,
                actor_user_id=principal.user_id,
            )
        )
        _audit(
            session,
            actor_id=principal.user_id,
            organization_id=organization_id,
            action="inventory.received",
            resource_type="inventory_batch",
            resource_id=batch.id,
            request_id=request_id,
            metadata={
                "purchase_order_id": str(order.id),
                "purchase_order_item_id": str(item.id),
                "quantity_delta": delta,
                "product_id": str(item.product_id),
            },
        )

    previous_status = order.status
    if all(item.received_quantity == item.quantity for item in items):
        order.status = OrderStatus.DELIVERED.value
    if changed:
        await session.flush()
        if order.status != previous_status:
            _audit(
                session,
                actor_id=principal.user_id,
                organization_id=organization_id,
                action="purchase_order.status_changed",
                resource_type="purchase_order",
                resource_id=order.id,
                request_id=request_id,
                metadata={"from": previous_status, "to": order.status, "reason": "shipment_received"},
            )
        _audit(
            session,
            actor_id=principal.user_id,
            organization_id=organization_id,
            action="purchase_order.received",
            resource_type="purchase_order",
            resource_id=order.id,
            request_id=request_id,
            metadata={
                "status": order.status,
                "received": {str(item.id): item.received_quantity for item in items},
            },
        )
        await session.flush()
    return await serialize_order(session, order)


async def list_pharmacy_inventory(
    session: AsyncSession, principal: Principal, organization_id: UUID
) -> list[InventoryBatchOut]:
    require_org_access(principal, organization_id, OrganizationType.PHARMACY, Permission.INVENTORY_RECEIVE)
    rows = (
        await session.execute(
            select(InventoryBatch, Product)
            .join(Product, Product.id == InventoryBatch.product_id)
            .where(InventoryBatch.organization_id == organization_id, InventoryBatch.quantity_on_hand > 0)
            .order_by(InventoryBatch.expiration_date.nulls_last(), Product.name)
        )
    ).all()
    return [
        InventoryBatchOut(
            id=batch.id,
            product_id=product.id,
            product_name=product.name,
            product_sku=product.sku,
            batch_number=batch.batch_number,
            expiration_date=batch.expiration_date,
            quantity_on_hand=batch.quantity_on_hand,
            unit_cost=batch.unit_cost,
            supplier_id=batch.supplier_id,
            purchase_order_item_id=batch.purchase_order_item_id,
            updated_at=batch.updated_at,
        )
        for batch, product in rows
    ]


async def list_inventory_movements(
    session: AsyncSession, principal: Principal, organization_id: UUID
) -> list[InventoryMovementOut]:
    require_org_access(principal, organization_id, OrganizationType.PHARMACY, Permission.INVENTORY_RECEIVE)
    rows = (
        await session.execute(
            select(InventoryMovement)
            .where(InventoryMovement.organization_id == organization_id)
            .order_by(InventoryMovement.created_at.desc())
            .limit(200)
        )
    ).scalars().all()
    return [InventoryMovementOut.model_validate(row) for row in rows]
