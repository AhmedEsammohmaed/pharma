"""Create persistent, idempotent procurement demo records in PostgreSQL.

Run from ``apps/api`` with ``SEED_DATABASE_URL`` and ``DEMO_USER_EMAIL`` set.
The database URL must be an operator-only migration/seed connection. It is
never read by the web application.
"""

import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.session import to_async_dsn
from app.modules.identity.models import AuditLog, Organization, OrganizationMember
from app.modules.procurement.models import (
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    SupplierInventoryBatch,
    SupplierProduct,
)


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Set {name} before running the demo seed.")
    return value


async def seed() -> None:
    database_url = to_async_dsn(required_env("SEED_DATABASE_URL"))
    user_email = required_env("DEMO_USER_EMAIL").lower()
    engine = create_async_engine(database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session, session.begin():
            user_id = await session.scalar(
                text("SELECT id FROM auth.users WHERE lower(email) = :email LIMIT 1"),
                {"email": user_email},
            )
            if user_id is None:
                raise SystemExit(
                    "No Supabase auth user matches DEMO_USER_EMAIL. Create/sign in the demo user first."
                )

            pharmacy = await get_or_create_org(
                session, "demo-community-pharmacy", "Demo Community Pharmacy", "pharmacy", user_id
            )
            supplier = await get_or_create_org(
                session, "demo-medical-supplies", "Demo Medical Supplies", "supplier", user_id
            )
            await ensure_membership(session, pharmacy, user_id, "pharmacy_admin")
            await ensure_membership(session, supplier, user_id, "supplier_admin")

            catalog = [
                ("DEMO-PAR-500", "Paracetamol 500 mg", "Paracetamol", "500 mg", "Tablet", "tablet", "Pain relief"),
                ("DEMO-IBU-400", "Ibuprofen 400 mg", "Ibuprofen", "400 mg", "Tablet", "tablet", "Pain relief"),
                ("DEMO-VIT-D", "Vitamin D3 1000 IU", "Cholecalciferol", "1000 IU", "Capsule", "capsule", "Vitamins"),
            ]
            products: list[Product] = []
            for sku, name, generic, strength, form, unit, category in catalog:
                product = await session.scalar(select(Product).where(Product.sku == sku))
                if product is None:
                    product = Product(
                        sku=sku,
                        name=name,
                        generic_name=generic,
                        strength=strength,
                        dosage_form=form,
                        unit=unit,
                        category=category,
                        active=True,
                    )
                    session.add(product)
                    await session.flush()
                products.append(product)

            offers = [
                (products[0], "SUP-PAR-500-A", "SUP-BATCH-PAR-2027-01", 240, Decimal("42.50"), 10, 3),
                (products[1], "SUP-IBU-400-A", "SUP-BATCH-IBU-2027-02", 120, Decimal("68.00"), 5, 4),
                (products[2], "SUP-VIT-D-A", "SUP-BATCH-VIT-2027-03", 80, Decimal("95.00"), 5, 2),
            ]
            inventory: list[SupplierInventoryBatch] = []
            for product, sku, batch_number, quantity, price, moq, lead_time in offers:
                supplier_product = await session.scalar(
                    select(SupplierProduct).where(
                        SupplierProduct.supplier_id == supplier.id,
                        SupplierProduct.product_id == product.id,
                    )
                )
                if supplier_product is None:
                    supplier_product = SupplierProduct(
                        supplier_id=supplier.id,
                        product_id=product.id,
                        supplier_sku=sku,
                        lead_time_days=lead_time,
                        active=True,
                        created_by=user_id,
                    )
                    session.add(supplier_product)
                    await session.flush()
                batch = await session.scalar(
                    select(SupplierInventoryBatch).where(
                        SupplierInventoryBatch.supplier_product_id == supplier_product.id,
                        SupplierInventoryBatch.batch_number == batch_number,
                    )
                )
                if batch is None:
                    batch = SupplierInventoryBatch(
                        supplier_product_id=supplier_product.id,
                        supplier_id=supplier.id,
                        product_id=product.id,
                        batch_number=batch_number,
                        available_quantity=quantity,
                        wholesale_price=price,
                        minimum_order_quantity=moq,
                        expiration_date=datetime.now(UTC).date() + timedelta(days=730),
                        status="available",
                    )
                    session.add(batch)
                    await session.flush()
                inventory.append(batch)

            order_number = "PO-DEMO-0001"
            order = await session.scalar(
                select(PurchaseOrder).where(
                    PurchaseOrder.organization_id == pharmacy.id,
                    PurchaseOrder.order_number == order_number,
                )
            )
            if order is None:
                order_lines = [(inventory[0], 20), (inventory[1], 10)]
                subtotal = sum((batch.wholesale_price * quantity for batch, quantity in order_lines), Decimal(0))
                order = PurchaseOrder(
                    organization_id=pharmacy.id,
                    supplier_id=supplier.id,
                    order_number=order_number,
                    status="PENDING",
                    subtotal=subtotal,
                    tax_total=Decimal(0),
                    total=subtotal,
                    notes="Persistent seed record for procurement demo",
                    created_by=user_id,
                )
                session.add(order)
                await session.flush()
                for batch, quantity in order_lines:
                    session.add(
                        PurchaseOrderItem(
                            purchase_order_id=order.id,
                            organization_id=pharmacy.id,
                            supplier_id=supplier.id,
                            supplier_inventory_id=batch.id,
                            product_id=batch.product_id,
                            quantity=quantity,
                            received_quantity=0,
                            unit_price=batch.wholesale_price,
                            line_total=batch.wholesale_price * quantity,
                        )
                    )
                session.add(
                    AuditLog(
                        organization_id=pharmacy.id,
                        actor_user_id=user_id,
                        action="purchase_order.seeded",
                        resource_type="purchase_order",
                        resource_id=str(order.id),
                        result="success",
                        metadata_={"seed": "procurement-demo", "supplier_id": str(supplier.id)},
                    )
                )
                session.add(
                    AuditLog(
                        organization_id=supplier.id,
                        actor_user_id=user_id,
                        action="supplier_inventory.seeded",
                        resource_type="supplier_inventory",
                        resource_id=str(supplier.id),
                        result="success",
                        metadata_={"seed": "procurement-demo", "batch_count": len(inventory)},
                    )
                )

            print(
                "Seeded persistent demo procurement data: "
                f"pharmacy={pharmacy.slug}, supplier={supplier.slug}, "
                f"products={len(products)}, supplier_batches={len(inventory)}, order={order.order_number}."
            )
    finally:
        await engine.dispose()


async def get_or_create_org(session, slug: str, name: str, org_type: str, user_id):
    organization = await session.scalar(
        select(Organization).where(Organization.slug == slug, Organization.deleted_at.is_(None))
    )
    if organization is None:
        organization = Organization(name=name, slug=slug, type=org_type, created_by=user_id)
        session.add(organization)
        await session.flush()
    return organization


async def ensure_membership(session, organization, user_id, role: str) -> None:
    membership = await session.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == organization.id,
            OrganizationMember.user_id == user_id,
        )
    )
    if membership is None:
        session.add(
            OrganizationMember(
                organization_id=organization.id,
                user_id=user_id,
                role=role,
                status="active",
            )
        )
    else:
        membership.role = role
        membership.status = "active"
        membership.deleted_at = None


if __name__ == "__main__":
    try:
        asyncio.run(seed())
    except KeyboardInterrupt:
        sys.exit(130)
