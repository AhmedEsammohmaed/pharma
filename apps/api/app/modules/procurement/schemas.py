from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class OrderStatus(StrEnum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    PROCESSING = "PROCESSING"
    READY = "READY"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    RETURNED = "RETURNED"


class SupplierInventoryStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class ProductOut(BaseModel):
    id: UUID
    sku: str
    name: str
    generic_name: str | None
    strength: str | None
    dosage_form: str | None
    unit: str
    category: str | None


class SupplierOut(BaseModel):
    id: UUID
    name: str
    slug: str
    lead_time_days: int
    listed_products: int


class SupplierInventoryCreate(BaseModel):
    product_id: UUID
    supplier_sku: str | None = Field(default=None, max_length=100)
    lead_time_days: int = Field(default=0, ge=0, le=365)
    batch_number: str | None = Field(default=None, max_length=120)
    available_quantity: int = Field(gt=0, le=2_000_000_000)
    wholesale_price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    minimum_order_quantity: int = Field(default=1, gt=0, le=2_000_000_000)
    expiration_date: date | None = None

    @field_validator("supplier_sku", "batch_number")
    @classmethod
    def strip_optional_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("expiration_date")
    @classmethod
    def expiration_must_be_future(cls, value: date | None) -> date | None:
        if value is not None and value <= datetime.now(UTC).date():
            raise ValueError("Expiration date must be in the future")
        return value


class SupplierInventoryUpdate(BaseModel):
    supplier_sku: str | None = Field(default=None, max_length=100)
    available_quantity: int | None = Field(default=None, ge=0, le=2_000_000_000)
    wholesale_price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    minimum_order_quantity: int | None = Field(default=None, gt=0, le=2_000_000_000)
    lead_time_days: int | None = Field(default=None, ge=0, le=365)
    expiration_date: date | None = None
    status: SupplierInventoryStatus | None = None

    @field_validator("expiration_date")
    @classmethod
    def expiration_must_be_future(cls, value: date | None) -> date | None:
        if value is not None and value <= datetime.now(UTC).date():
            raise ValueError("Expiration date must be in the future")
        return value

    @field_validator("supplier_sku")
    @classmethod
    def strip_supplier_sku(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def non_nullable_updates_are_not_null(self) -> "SupplierInventoryUpdate":
        for field in ("available_quantity", "wholesale_price", "minimum_order_quantity", "lead_time_days", "status"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class SupplierInventoryOut(BaseModel):
    id: UUID
    supplier_id: UUID
    supplier_name: str
    supplier_product_id: UUID
    product_id: UUID
    product_name: str
    product_sku: str
    unit: str
    supplier_sku: str | None
    batch_number: str | None
    available_quantity: int
    wholesale_price: Decimal
    minimum_order_quantity: int
    lead_time_days: int
    expiration_date: date | None
    status: SupplierInventoryStatus
    updated_at: datetime


class PurchaseOrderItemCreate(BaseModel):
    supplier_inventory_id: UUID
    quantity: int = Field(gt=0, le=2_000_000_000)


class PurchaseOrderCreate(BaseModel):
    supplier_id: UUID
    items: list[PurchaseOrderItemCreate] = Field(min_length=1, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("notes")
    @classmethod
    def strip_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def inventory_items_are_unique(self) -> "PurchaseOrderCreate":
        item_ids = [item.supplier_inventory_id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("Each supplier inventory batch may appear only once")
        return self


class PurchaseOrderUpdate(BaseModel):
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("notes")
    @classmethod
    def strip_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class UpdateOrderStatusRequest(BaseModel):
    status: OrderStatus


class ReceivePurchaseOrderItem(BaseModel):
    item_id: UUID
    received_quantity: int = Field(ge=0, le=2_000_000_000)


class ReceivePurchaseOrderRequest(BaseModel):
    # Each quantity is the cumulative received amount for that line. Replaying
    # the same request is safe and cannot add the same stock twice.
    items: list[ReceivePurchaseOrderItem] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def receive_items_are_unique(self) -> "ReceivePurchaseOrderRequest":
        item_ids = [item.item_id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("Each order line may appear only once")
        return self


class PurchaseOrderItemOut(BaseModel):
    id: UUID
    product_id: UUID
    product_name: str
    product_sku: str
    supplier_inventory_id: UUID
    batch_number: str | None
    quantity: int
    received_quantity: int
    unit_price: Decimal
    line_total: Decimal


class PurchaseOrderOut(BaseModel):
    id: UUID
    organization_id: UUID
    supplier_id: UUID
    supplier_name: str
    order_number: str
    status: OrderStatus
    subtotal: Decimal
    tax_total: Decimal
    total: Decimal
    notes: str | None
    created_at: datetime
    updated_at: datetime
    items: list[PurchaseOrderItemOut]


class InventoryBatchOut(BaseModel):
    id: UUID
    product_id: UUID
    product_name: str
    product_sku: str
    batch_number: str | None
    expiration_date: date | None
    quantity_on_hand: int
    unit_cost: Decimal
    supplier_id: UUID
    purchase_order_item_id: UUID
    updated_at: datetime


class InventoryMovementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    inventory_batch_id: UUID
    purchase_order_item_id: UUID
    movement_type: str
    quantity_delta: int
    unit_cost: Decimal
    actor_user_id: UUID
    created_at: datetime
