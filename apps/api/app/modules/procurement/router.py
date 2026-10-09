from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_authenticated_session, get_principal
from app.auth.principal import Principal
from app.core.errors import AppError
from app.modules.procurement.schemas import (
    InventoryBatchOut,
    InventoryMovementOut,
    OrderStatus,
    ProductOut,
    PurchaseOrderCreate,
    PurchaseOrderOut,
    PurchaseOrderUpdate,
    ReceivePurchaseOrderRequest,
    SupplierInventoryCreate,
    SupplierInventoryOut,
    SupplierInventoryUpdate,
    SupplierOut,
    UpdateOrderStatusRequest,
)
from app.modules.procurement.service import (
    create_purchase_order,
    create_supplier_inventory,
    delete_supplier_inventory,
    get_purchase_order,
    list_inventory_movements,
    list_pharmacy_inventory,
    list_products,
    list_purchase_orders,
    list_supplier_inventory,
    list_suppliers,
    receive_purchase_order,
    transition_purchase_order,
    update_purchase_order,
    update_supplier_inventory,
)

router = APIRouter(prefix="/api/v1")
OrganizationHeader = Annotated[UUID, Header(alias="X-Organization-Id")]
AuthenticatedPrincipal = Annotated[Principal, Depends(get_principal)]
BusinessSession = Annotated[AsyncSession, Depends(get_authenticated_session, scope="function")]


@router.get("/products", response_model=list[ProductOut])
async def products(
    organization_id: OrganizationHeader,
    principal: AuthenticatedPrincipal,
    session: BusinessSession,
) -> list[ProductOut]:
    return await list_products(session, principal, organization_id)


@router.get("/suppliers", response_model=list[SupplierOut])
async def suppliers(
    organization_id: OrganizationHeader,
    principal: AuthenticatedPrincipal,
    session: BusinessSession,
) -> list[SupplierOut]:
    return await list_suppliers(session, principal, organization_id)


@router.get("/suppliers/{supplier_id}/inventory", response_model=list[SupplierInventoryOut])
async def supplier_inventory(
    supplier_id: UUID,
    organization_id: OrganizationHeader,
    principal: AuthenticatedPrincipal,
    session: BusinessSession,
) -> list[SupplierInventoryOut]:
    return await list_supplier_inventory(session, principal, organization_id, supplier_id)


@router.post(
    "/suppliers/{supplier_id}/inventory",
    response_model=SupplierInventoryOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_supplier_inventory(
    supplier_id: UUID,
    payload: SupplierInventoryCreate,
    request: Request,
    organization_id: OrganizationHeader,
    principal: AuthenticatedPrincipal,
    session: BusinessSession,
) -> SupplierInventoryOut:
    if supplier_id != organization_id:
        raise AppError(404, "not_found", "Supplier not found")
    return await create_supplier_inventory(
        session,
        principal,
        organization_id,
        payload,
        getattr(request.state, "request_id", None),
    )


@router.patch("/suppliers/{supplier_id}/inventory/{inventory_id}", response_model=SupplierInventoryOut)
async def patch_supplier_inventory(
    supplier_id: UUID,
    inventory_id: UUID,
    payload: SupplierInventoryUpdate,
    request: Request,
    organization_id: OrganizationHeader,
    principal: AuthenticatedPrincipal,
    session: BusinessSession,
) -> SupplierInventoryOut:
    if supplier_id != organization_id:
        raise AppError(404, "not_found", "Supplier inventory item not found")
    return await update_supplier_inventory(
        session,
        principal,
        organization_id,
        inventory_id,
        payload,
        getattr(request.state, "request_id", None),
    )


@router.delete("/suppliers/{supplier_id}/inventory/{inventory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_supplier_inventory(
    supplier_id: UUID,
    inventory_id: UUID,
    request: Request,
    organization_id: OrganizationHeader,
    principal: AuthenticatedPrincipal,
    session: BusinessSession,
) -> Response:
    if supplier_id != organization_id:
        raise AppError(404, "not_found", "Supplier inventory item not found")
    await delete_supplier_inventory(
        session,
        principal,
        organization_id,
        inventory_id,
        getattr(request.state, "request_id", None),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/orders", response_model=list[PurchaseOrderOut])
async def orders(
    organization_id: OrganizationHeader,
    principal: AuthenticatedPrincipal,
    session: BusinessSession,
) -> list[PurchaseOrderOut]:
    return await list_purchase_orders(session, principal, organization_id)


@router.post("/orders", response_model=PurchaseOrderOut, status_code=status.HTTP_201_CREATED)
async def add_order(
    payload: PurchaseOrderCreate,
    request: Request,
    organization_id: OrganizationHeader,
    principal: AuthenticatedPrincipal,
    session: BusinessSession,
) -> PurchaseOrderOut:
    return await create_purchase_order(
        session,
        principal,
        organization_id,
        payload,
        getattr(request.state, "request_id", None),
    )


@router.get("/orders/{order_id}", response_model=PurchaseOrderOut)
async def order(
    order_id: UUID,
    organization_id: OrganizationHeader,
    principal: AuthenticatedPrincipal,
    session: BusinessSession,
) -> PurchaseOrderOut:
    return await get_purchase_order(session, principal, organization_id, order_id)


@router.patch("/orders/{order_id}", response_model=PurchaseOrderOut)
async def patch_order(
    order_id: UUID,
    payload: PurchaseOrderUpdate,
    request: Request,
    organization_id: OrganizationHeader,
    principal: AuthenticatedPrincipal,
    session: BusinessSession,
) -> PurchaseOrderOut:
    return await update_purchase_order(
        session,
        principal,
        organization_id,
        order_id,
        payload,
        getattr(request.state, "request_id", None),
    )


@router.post("/orders/{order_id}/status", response_model=PurchaseOrderOut)
async def set_order_status(
    order_id: UUID,
    payload: UpdateOrderStatusRequest,
    request: Request,
    organization_id: OrganizationHeader,
    principal: AuthenticatedPrincipal,
    session: BusinessSession,
) -> PurchaseOrderOut:
    return await transition_purchase_order(
        session,
        principal,
        organization_id,
        order_id,
        payload.status,
        getattr(request.state, "request_id", None),
    )


@router.post("/orders/{order_id}/confirm", response_model=PurchaseOrderOut)
async def confirm_order(
    order_id: UUID,
    request: Request,
    organization_id: OrganizationHeader,
    principal: AuthenticatedPrincipal,
    session: BusinessSession,
) -> PurchaseOrderOut:
    return await transition_purchase_order(
        session,
        principal,
        organization_id,
        order_id,
        OrderStatus.CONFIRMED,
        getattr(request.state, "request_id", None),
    )


@router.post("/orders/{order_id}/cancel", response_model=PurchaseOrderOut)
async def cancel_order(
    order_id: UUID,
    request: Request,
    organization_id: OrganizationHeader,
    principal: AuthenticatedPrincipal,
    session: BusinessSession,
) -> PurchaseOrderOut:
    return await transition_purchase_order(
        session,
        principal,
        organization_id,
        order_id,
        OrderStatus.CANCELLED,
        getattr(request.state, "request_id", None),
    )


@router.post("/orders/{order_id}/receive", response_model=PurchaseOrderOut)
async def receive_order(
    order_id: UUID,
    payload: ReceivePurchaseOrderRequest,
    request: Request,
    organization_id: OrganizationHeader,
    principal: AuthenticatedPrincipal,
    session: BusinessSession,
) -> PurchaseOrderOut:
    return await receive_purchase_order(
        session,
        principal,
        organization_id,
        order_id,
        payload,
        getattr(request.state, "request_id", None),
    )


@router.get("/inventory/batches", response_model=list[InventoryBatchOut])
async def inventory_batches(
    organization_id: OrganizationHeader,
    principal: AuthenticatedPrincipal,
    session: BusinessSession,
) -> list[InventoryBatchOut]:
    return await list_pharmacy_inventory(session, principal, organization_id)


@router.get("/inventory/movements", response_model=list[InventoryMovementOut])
async def inventory_movements(
    organization_id: OrganizationHeader,
    principal: AuthenticatedPrincipal,
    session: BusinessSession,
) -> list[InventoryMovementOut]:
    return await list_inventory_movements(session, principal, organization_id)
