from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.identity.models import Base


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("char_length(btrim(sku)) > 0", name="products_sku_not_blank"),
        CheckConstraint("char_length(btrim(name)) > 0", name="products_name_not_blank"),
        CheckConstraint("char_length(btrim(unit)) > 0", name="products_unit_not_blank"),
        Index("products_active_name_idx", "name", postgresql_where=text("active")),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    sku: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(240))
    generic_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    strength: Mapped[str | None] = mapped_column(String(120), nullable=True)
    dosage_form: Mapped[str | None] = mapped_column(String(120), nullable=True)
    unit: Mapped[str] = mapped_column(String(60), default="unit")
    category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SupplierProduct(Base):
    __tablename__ = "supplier_products"
    __table_args__ = (
        CheckConstraint("lead_time_days >= 0", name="supplier_products_lead_time_nonnegative"),
        UniqueConstraint("supplier_id", "product_id", name="supplier_products_org_product_unique"),
        UniqueConstraint("id", "supplier_id", "product_id", name="supplier_products_reference_unique"),
        Index("supplier_products_product_active_idx", "product_id", "supplier_id", postgresql_where=text("active")),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    supplier_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"))
    product_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"))
    supplier_sku: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lead_time_days: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("auth.users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class SupplierInventoryBatch(Base):
    __tablename__ = "supplier_inventory_batches"
    __table_args__ = (
        ForeignKeyConstraint(
            ["supplier_product_id", "supplier_id", "product_id"],
            ["supplier_products.id", "supplier_products.supplier_id", "supplier_products.product_id"],
            ondelete="RESTRICT",
            name="supplier_inventory_supplier_product_fk",
        ),
        CheckConstraint("available_quantity >= 0", name="supplier_inventory_quantity_nonnegative"),
        CheckConstraint(
            "reserved_quantity >= 0 AND reserved_quantity <= available_quantity",
            name="supplier_inventory_reserved_range",
        ),
        CheckConstraint("wholesale_price >= 0", name="supplier_inventory_price_nonnegative"),
        CheckConstraint("minimum_order_quantity > 0", name="supplier_inventory_moq_positive"),
        CheckConstraint("status IN ('available', 'unavailable')", name="supplier_inventory_status_valid"),
        UniqueConstraint("id", "supplier_id", "product_id", name="supplier_inventory_reference_unique"),
        Index(
            "supplier_inventory_available_idx",
            "supplier_id",
            "product_id",
            "expiration_date",
            postgresql_where=text("status = 'available' AND available_quantity > 0"),
        ),
        Index(
            "supplier_inventory_unbatched_unique_idx",
            "supplier_product_id",
            unique=True,
            postgresql_where=text("batch_number IS NULL"),
        ),
        Index(
            "supplier_inventory_batch_number_unique_idx",
            "supplier_product_id",
            "batch_number",
            unique=True,
            postgresql_where=text("batch_number IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    supplier_product_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    supplier_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"))
    product_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"))
    batch_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    available_quantity: Mapped[int] = mapped_column(Integer)
    reserved_quantity: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    wholesale_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    minimum_order_quantity: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    expiration_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="available", server_default="available")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        UniqueConstraint("organization_id", "order_number", name="purchase_orders_org_order_number_unique"),
        UniqueConstraint("id", "organization_id", "supplier_id", name="purchase_orders_reference_unique"),
        CheckConstraint("char_length(btrim(order_number)) > 0", name="purchase_orders_number_not_blank"),
        CheckConstraint(
            "status IN ('PENDING', 'CONFIRMED', 'PROCESSING', 'READY', 'SHIPPED', 'DELIVERED', 'CANCELLED', 'RETURNED')",
            name="purchase_orders_status_valid",
        ),
        CheckConstraint("subtotal >= 0 AND tax_total >= 0 AND total >= 0", name="purchase_orders_totals_nonnegative"),
        CheckConstraint("total = subtotal + tax_total", name="purchase_orders_total_matches"),
        Index("purchase_orders_buyer_recent_idx", "organization_id", "created_at"),
        Index("purchase_orders_supplier_recent_idx", "supplier_id", "created_at"),
        Index("purchase_orders_status_recent_idx", "status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"))
    supplier_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"))
    order_number: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="PENDING", server_default="PENDING")
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal(0), server_default="0")
    tax_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal(0), server_default="0")
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal(0), server_default="0")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("auth.users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class PurchaseOrderItem(Base):
    __tablename__ = "purchase_order_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["purchase_order_id", "organization_id", "supplier_id"],
            ["purchase_orders.id", "purchase_orders.organization_id", "purchase_orders.supplier_id"],
            ondelete="CASCADE",
            name="purchase_order_items_order_fk",
        ),
        ForeignKeyConstraint(
            ["supplier_inventory_id", "supplier_id", "product_id"],
            ["supplier_inventory_batches.id", "supplier_inventory_batches.supplier_id", "supplier_inventory_batches.product_id"],
            ondelete="RESTRICT",
            name="purchase_order_items_supplier_inventory_fk",
        ),
        CheckConstraint("quantity > 0", name="purchase_order_items_quantity_positive"),
        CheckConstraint("received_quantity >= 0 AND received_quantity <= quantity", name="purchase_order_items_received_range"),
        CheckConstraint("unit_price >= 0", name="purchase_order_items_price_nonnegative"),
        CheckConstraint("line_total = quantity * unit_price", name="purchase_order_items_total_matches"),
        UniqueConstraint(
            "purchase_order_id",
            "supplier_inventory_id",
            name="purchase_order_items_order_batch_unique",
        ),
        UniqueConstraint("id", "organization_id", "supplier_id", "product_id", name="purchase_order_items_reference_unique"),
        Index("purchase_order_items_product_idx", "product_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    purchase_order_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    supplier_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    supplier_inventory_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    product_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"))
    quantity: Mapped[int] = mapped_column(Integer)
    received_quantity: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    line_total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class InventoryBatch(Base):
    __tablename__ = "inventory_batches"
    __table_args__ = (
        ForeignKeyConstraint(
            ["purchase_order_item_id", "organization_id", "supplier_id", "product_id"],
            [
                "purchase_order_items.id",
                "purchase_order_items.organization_id",
                "purchase_order_items.supplier_id",
                "purchase_order_items.product_id",
            ],
            ondelete="RESTRICT",
            name="inventory_batches_source_item_fk",
        ),
        CheckConstraint("quantity_on_hand >= 0", name="inventory_batches_quantity_nonnegative"),
        CheckConstraint("unit_cost >= 0", name="inventory_batches_cost_nonnegative"),
        Index("inventory_batches_org_product_idx", "organization_id", "product_id", "expiration_date"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"))
    product_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"))
    supplier_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"))
    purchase_order_item_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), unique=True)
    batch_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    expiration_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    quantity_on_hand: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InventoryMovement(Base):
    __tablename__ = "inventory_movements"
    __table_args__ = (
        CheckConstraint("movement_type IN ('receipt', 'return', 'adjustment')", name="inventory_movements_type_valid"),
        CheckConstraint("quantity_delta <> 0", name="inventory_movements_nonzero"),
        CheckConstraint("unit_cost >= 0", name="inventory_movements_cost_nonnegative"),
        Index("inventory_movements_org_product_recent_idx", "organization_id", "product_id", "created_at"),
        Index("inventory_movements_order_item_idx", "purchase_order_item_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"))
    product_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"))
    inventory_batch_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("inventory_batches.id", ondelete="RESTRICT"))
    purchase_order_item_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("purchase_order_items.id", ondelete="RESTRICT"))
    movement_type: Mapped[str] = mapped_column(String(20))
    quantity_delta: Mapped[int] = mapped_column(Integer)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    actor_user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("auth.users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
