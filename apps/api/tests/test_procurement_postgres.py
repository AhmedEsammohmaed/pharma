"""PostgreSQL integration checks; requires an isolated disposable test database."""

import os
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.session import to_async_dsn

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")
TEST_DATABASE_URL_RLS = os.environ.get("TEST_DATABASE_URL_RLS", "")
TEST_USER_EMAIL = os.environ.get("TEST_DATABASE_USER_EMAIL", "")


@pytest.mark.asyncio
@pytest.mark.skipif(
    not TEST_DATABASE_URL or not TEST_USER_EMAIL,
    reason="set TEST_DATABASE_URL and TEST_DATABASE_USER_EMAIL for a migrated disposable PostgreSQL database",
)
async def test_postgres_procurement_constraints_ledger_and_rollback() -> None:
    engine = create_async_engine(to_async_dsn(TEST_DATABASE_URL), pool_pre_ping=True)
    pharmacy_id, supplier_id = uuid4(), uuid4()
    product_id, supplier_product_id, supplier_batch_id = uuid4(), uuid4(), uuid4()
    order_id, item_id, pharmacy_batch_id, movement_id = (uuid4() for _ in range(4))
    sku = f"TEST-{uuid4().hex}"
    order_number = f"PO-TEST-{uuid4().hex[:12]}"

    try:
        async with engine.connect() as connection:
            user_id = await connection.scalar(
                text("SELECT id FROM auth.users WHERE lower(email) = lower(:email) LIMIT 1"),
                {"email": TEST_USER_EMAIL},
            )
            assert user_id is not None, "TEST_DATABASE_USER_EMAIL must identify an existing auth.users row"

            rls_rows = (
                await connection.execute(
                    text(
                        "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
                        "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                        "WHERE n.nspname = 'public' AND c.relname IN "
                        "('supplier_inventory_batches', 'purchase_orders', 'purchase_order_items', 'inventory_batches', 'inventory_movements')"
                    ),
                )
            ).all()
            assert len(rls_rows) == 5, "apply the procurement migration before running these checks"
            assert all(enabled and forced for _, enabled, forced in rls_rows)

            await connection.rollback()
            transaction = await connection.begin()
            try:
                await connection.execute(
                    text(
                        "INSERT INTO public.organizations (id, name, slug, type, created_by) "
                        "VALUES (:id, :name, :slug, CAST(:type AS public.organization_type), :user_id)"
                    ),
                    [
                        {"id": pharmacy_id, "name": "Test Pharmacy", "slug": f"test-pharmacy-{pharmacy_id.hex}", "type": "pharmacy", "user_id": user_id},
                        {"id": supplier_id, "name": "Test Supplier", "slug": f"test-supplier-{supplier_id.hex}", "type": "supplier", "user_id": user_id},
                    ],
                )
                await connection.execute(
                    text("INSERT INTO public.products (id, sku, name, unit) VALUES (:id, :sku, 'Test product', 'unit')"),
                    {"id": product_id, "sku": sku},
                )
                await connection.execute(
                    text(
                        "INSERT INTO public.supplier_products (id, supplier_id, product_id, created_by) "
                        "VALUES (:id, :supplier_id, :product_id, :user_id)"
                    ),
                    {"id": supplier_product_id, "supplier_id": supplier_id, "product_id": product_id, "user_id": user_id},
                )
                await connection.execute(
                    text(
                        "INSERT INTO public.supplier_inventory_batches "
                        "(id, supplier_product_id, supplier_id, product_id, batch_number, available_quantity, wholesale_price) "
                        "VALUES (:id, :supplier_product_id, :supplier_id, :product_id, 'BATCH-1', 20, 12.50)"
                    ),
                    {"id": supplier_batch_id, "supplier_product_id": supplier_product_id, "supplier_id": supplier_id, "product_id": product_id},
                )
                await connection.execute(
                    text(
                        "INSERT INTO public.purchase_orders "
                        "(id, organization_id, supplier_id, order_number, subtotal, total, created_by) "
                        "VALUES (:id, :pharmacy_id, :supplier_id, :order_number, 25.00, 25.00, :user_id)"
                    ),
                    {"id": order_id, "pharmacy_id": pharmacy_id, "supplier_id": supplier_id, "order_number": order_number, "user_id": user_id},
                )
                await connection.execute(
                    text(
                        "INSERT INTO public.purchase_order_items "
                        "(id, purchase_order_id, organization_id, supplier_id, supplier_inventory_id, product_id, quantity, unit_price, line_total) "
                        "VALUES (:id, :order_id, :pharmacy_id, :supplier_id, :batch_id, :product_id, 2, 12.50, 25.00)"
                    ),
                    {"id": item_id, "order_id": order_id, "pharmacy_id": pharmacy_id, "supplier_id": supplier_id, "batch_id": supplier_batch_id, "product_id": product_id},
                )

                with pytest.raises(IntegrityError):
                    async with connection.begin_nested():
                        await connection.execute(
                            text(
                                "INSERT INTO public.purchase_orders "
                                "(id, organization_id, supplier_id, order_number, subtotal, total, created_by) "
                                "VALUES (:id, :pharmacy_id, :supplier_id, :order_number, 1, 1, :user_id)"
                            ),
                            {"id": uuid4(), "pharmacy_id": pharmacy_id, "supplier_id": supplier_id, "order_number": order_number, "user_id": user_id},
                        )

                with pytest.raises(IntegrityError):
                    async with connection.begin_nested():
                        await connection.execute(
                            text(
                                "INSERT INTO public.supplier_products (supplier_id, product_id, created_by) "
                                "VALUES (:missing_supplier, :product_id, :user_id)"
                            ),
                            {"missing_supplier": uuid4(), "product_id": product_id, "user_id": user_id},
                        )

                await connection.execute(
                    text(
                        "INSERT INTO public.inventory_batches "
                        "(id, organization_id, product_id, supplier_id, purchase_order_item_id, quantity_on_hand, unit_cost) "
                        "VALUES (:id, :pharmacy_id, :product_id, :supplier_id, :item_id, 2, 12.50)"
                    ),
                    {"id": pharmacy_batch_id, "pharmacy_id": pharmacy_id, "product_id": product_id, "supplier_id": supplier_id, "item_id": item_id},
                )
                await connection.execute(
                    text(
                        "INSERT INTO public.inventory_movements "
                        "(id, organization_id, product_id, inventory_batch_id, purchase_order_item_id, movement_type, quantity_delta, unit_cost, actor_user_id) "
                        "VALUES (:id, :pharmacy_id, :product_id, :batch_id, :item_id, 'receipt', 2, 12.50, :user_id)"
                    ),
                    {"id": movement_id, "pharmacy_id": pharmacy_id, "product_id": product_id, "batch_id": pharmacy_batch_id, "item_id": item_id, "user_id": user_id},
                )
                connected = await connection.scalar(
                    text(
                        "SELECT count(*) FROM public.inventory_movements m "
                        "JOIN public.inventory_batches b ON b.id = m.inventory_batch_id "
                        "JOIN public.purchase_order_items i ON i.id = m.purchase_order_item_id "
                        "WHERE m.id = :movement_id AND b.purchase_order_item_id = i.id AND i.purchase_order_id = :order_id"
                    ),
                    {"movement_id": movement_id, "order_id": order_id},
                )
                assert connected == 1, "movement must reference its pharmacy batch and order item"

                await transaction.rollback()
            except Exception:
                if transaction.is_active:
                    await transaction.rollback()
                raise

            remaining = await connection.scalar(text("SELECT count(*) FROM public.products WHERE sku = :sku"), {"sku": sku})
            assert remaining == 0, "the integration fixture must roll back all writes"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.skipif(
    not TEST_DATABASE_URL or not TEST_DATABASE_URL_RLS or not TEST_USER_EMAIL,
    reason="set admin and restricted TEST_DATABASE_URLs plus TEST_DATABASE_USER_EMAIL to test PostgreSQL RLS",
)
async def test_postgres_rls_blocks_cross_tenant_order_and_supplier_inventory_access() -> None:
    admin_engine = create_async_engine(to_async_dsn(TEST_DATABASE_URL), pool_pre_ping=True)
    rls_engine = create_async_engine(to_async_dsn(TEST_DATABASE_URL_RLS), pool_pre_ping=True)
    pharmacy_a, pharmacy_b, supplier_a, supplier_b = (uuid4() for _ in range(4))
    product_id = uuid4()
    supplier_product_a, supplier_product_b = uuid4(), uuid4()
    batch_a, batch_b, order_b = uuid4(), uuid4(), uuid4()

    try:
        async with admin_engine.begin() as connection:
            user_id = await connection.scalar(
                text("SELECT id FROM auth.users WHERE lower(email) = lower(:email) LIMIT 1"),
                {"email": TEST_USER_EMAIL},
            )
            assert user_id is not None, "TEST_DATABASE_USER_EMAIL must identify an existing auth.users row"
            organizations = [
                (pharmacy_a, "pharmacy", "RLS Pharmacy A"),
                (pharmacy_b, "pharmacy", "RLS Pharmacy B"),
                (supplier_a, "supplier", "RLS Supplier A"),
                (supplier_b, "supplier", "RLS Supplier B"),
            ]
            for organization_id, org_type, name in organizations:
                await connection.execute(
                    text(
                        "INSERT INTO public.organizations (id, name, slug, type, created_by) "
                        "VALUES (:id, :name, :slug, CAST(:type AS public.organization_type), :user_id)"
                    ),
                    {"id": organization_id, "name": name, "slug": f"{name.lower().replace(' ', '-')}-{organization_id.hex}", "type": org_type, "user_id": user_id},
                )
            for organization_id, role in ((pharmacy_a, "pharmacy_admin"), (supplier_a, "supplier_admin")):
                await connection.execute(
                    text(
                        "INSERT INTO public.organization_members (organization_id, user_id, role, status) "
                        "VALUES (:organization_id, :user_id, CAST(:role AS public.organization_role), 'active')"
                    ),
                    {"organization_id": organization_id, "user_id": user_id, "role": role},
                )
            await connection.execute(
                text("INSERT INTO public.products (id, sku, name, unit) VALUES (:id, :sku, 'RLS product', 'unit')"),
                {"id": product_id, "sku": f"RLS-{product_id.hex}"},
            )
            for supplier_id, supplier_product_id, batch_id, sku in (
                (supplier_a, supplier_product_a, batch_a, "A"),
                (supplier_b, supplier_product_b, batch_b, "B"),
            ):
                await connection.execute(
                    text(
                        "INSERT INTO public.supplier_products (id, supplier_id, product_id, active, created_by) "
                        "VALUES (:id, :supplier_id, :product_id, :active, :user_id)"
                    ),
                    {
                        "id": supplier_product_id,
                        "supplier_id": supplier_id,
                        "product_id": product_id,
                        "active": supplier_id == supplier_a,
                        "user_id": user_id,
                    },
                )
                await connection.execute(
                    text(
                        "INSERT INTO public.supplier_inventory_batches "
                        "(id, supplier_product_id, supplier_id, product_id, batch_number, available_quantity, wholesale_price, status) "
                        "VALUES (:id, :supplier_product_id, :supplier_id, :product_id, :batch_number, 20, 12.50, :status)"
                    ),
                    {
                        "id": batch_id,
                        "supplier_product_id": supplier_product_id,
                        "supplier_id": supplier_id,
                        "product_id": product_id,
                        "batch_number": f"RLS-{sku}",
                        "status": "available" if supplier_id == supplier_a else "unavailable",
                    },
                )
            await connection.execute(
                text(
                    "INSERT INTO public.purchase_orders "
                    "(id, organization_id, supplier_id, order_number, subtotal, total, created_by) "
                    "VALUES (:id, :pharmacy_id, :supplier_id, :order_number, 12.50, 12.50, :user_id)"
                ),
                {"id": order_b, "pharmacy_id": pharmacy_b, "supplier_id": supplier_b, "order_number": f"RLS-{order_b.hex}", "user_id": user_id},
            )

        async with rls_engine.connect() as connection, connection.begin():
            await connection.execute(
                text("SELECT set_config('app.user_id', :user_id, true), set_config('app.organization_id', :org_id, true)"),
                {"user_id": str(user_id), "org_id": str(pharmacy_a)},
            )
            visible_order = await connection.scalar(
                text("SELECT count(*) FROM public.purchase_orders WHERE id = :id"), {"id": order_b}
            )
            assert visible_order == 0, "Pharmacy A must not read Pharmacy B's order"
            hidden_offer = await connection.scalar(
                text("SELECT count(*) FROM public.supplier_products WHERE id = :id"), {"id": supplier_product_b}
            )
            assert hidden_offer == 0, "Pharmacy A must not read inactive supplier offers without sellable stock"
            hidden_batch = await connection.scalar(
                text("SELECT count(*) FROM public.supplier_inventory_batches WHERE id = :id"), {"id": batch_b}
            )
            assert hidden_batch == 0, "Pharmacy A must not read unavailable supplier inventory"
            updated_order = await connection.scalar(
                text("UPDATE public.purchase_orders SET notes = 'IDOR attempt' WHERE id = :id RETURNING id"),
                {"id": order_b},
            )
            assert updated_order is None, "Pharmacy A must not modify Pharmacy B's order"

            await connection.execute(
                text("SELECT set_config('app.organization_id', :org_id, true)"), {"org_id": str(supplier_a)}
            )
            visible_batch = await connection.scalar(
                text("SELECT count(*) FROM public.supplier_inventory_batches WHERE id = :id"), {"id": batch_b}
            )
            assert visible_batch == 0, "Supplier A must not read Supplier B's private inventory"

    finally:
        async with admin_engine.begin() as connection:
            await connection.execute(text("DELETE FROM public.purchase_orders WHERE id = :id"), {"id": order_b})
            await connection.execute(
                text("DELETE FROM public.supplier_inventory_batches WHERE id IN (:batch_a, :batch_b)"),
                {"batch_a": batch_a, "batch_b": batch_b},
            )
            await connection.execute(
                text("DELETE FROM public.supplier_products WHERE id IN (:product_a, :product_b)"),
                {"product_a": supplier_product_a, "product_b": supplier_product_b},
            )
            await connection.execute(text("DELETE FROM public.products WHERE id = :id"), {"id": product_id})
            await connection.execute(
                text("DELETE FROM public.organizations WHERE id IN (:pharmacy_a, :pharmacy_b, :supplier_a, :supplier_b)"),
                {"pharmacy_a": pharmacy_a, "pharmacy_b": pharmacy_b, "supplier_a": supplier_a, "supplier_b": supplier_b},
            )
        await rls_engine.dispose()
        await admin_engine.dispose()
