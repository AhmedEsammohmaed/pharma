# Database

PostgreSQL is hosted through Supabase. Supabase Auth owns credentials; application identity and pharmacy/supplier organizations live in `public`. SQL migrations are applied explicitly and are never run at API startup.

## Identity and tenancy

The first migration creates `profiles`, `organizations`, `organization_members`, `organization_invites`, and `audit_logs`. `organizations.id` is the tenant boundary; there is no separate tenant ID. A pharmacy or supplier organization is resolved from the verified user membership, and an `X-Organization-Id` header is only a requested context.

## Procurement schema

Migration `supabase/migrations/20261007130000_procurement.sql` adds:

| Table | Purpose |
| --- | --- |
| `products` | Shared active pharmaceutical product catalog; one product entity is reused across suppliers and pharmacies. |
| `supplier_products` | Supplier-owned relationship to a catalog product, including supplier SKU and lead time. |
| `supplier_inventory_batches` | Supplier stock by batch, with physical quantity, reserved quantity, price, MOQ, expiry, availability, and soft deletion. |
| `purchase_orders` | Pharmacy-owned order addressed to a supplier, with immutable order number, status, totals, notes, and creator. |
| `purchase_order_items` | Product lines that snapshot supplier batch, quantity, and unit price at order time. |
| `inventory_batches` | Pharmacy stock batches created from received purchase order lines. |
| `inventory_movements` | Append-only receipt ledger tied to a pharmacy, stock batch, order line, and actor. |

Foreign keys and composite references ensure an order line's supplier, product, and source batch agree. Unique constraints prevent duplicate supplier batches and order numbers. Checks constrain quantities, reservations, prices, totals, and order status. Read indexes cover tenant, supplier, product, and recent order/movement lookups.

Supplier `available_quantity` is physical on-hand stock. `reserved_quantity` is committed to confirmed orders. The API reports sellable quantity as on-hand minus reserved. Confirmation locks the order and supplier batches and reserves stock atomically. Cancellation before shipment releases it. Shipping reduces both on-hand and reserved stock. A shipment returned before any pharmacy receipt restores supplier stock.

## Purchase order lifecycle

| From | To |
| --- | --- |
| `PENDING` | `CONFIRMED`, `CANCELLED` |
| `CONFIRMED` | `PROCESSING`, `CANCELLED` |
| `PROCESSING` | `READY`, `CANCELLED` |
| `READY` | `SHIPPED`, `CANCELLED` |
| `SHIPPED` | `DELIVERED`, `RETURNED` |
| `DELIVERED`, `CANCELLED`, `RETURNED` | No transitions |

The API does not allow setting `DELIVERED` directly. Receiving accepts cumulative quantities for every order line, rejects decreases or over-receipt, and applies only each new quantity delta. A receipt transaction creates or updates pharmacy batches, appends movement rows, updates received quantities and order status, and writes audit events together. Replaying the same cumulative receipt does not add stock twice. Receiving the full quantity moves the order to `DELIVERED`; partial receipt leaves it `SHIPPED` for follow-up.

The app currently has no tax configuration, so purchase-order tax is zero. Subtotals and totals are calculated server-side from current supplier prices; each line preserves its transaction-time unit price.

## Authorization and RLS

FastAPI verifies the Supabase access token, loads active memberships, enforces role and organization type, scopes each query by the selected organization, and sets transaction-local `app.user_id` and `app.organization_id`. Procurement rows have forced RLS policies as a second tenant boundary. Pharmacy users can read current sellable supplier offers and orders addressed to their pharmacy. A supplier sees its own inventory and only orders addressed to it. Pharmacy inventory and movements are pharmacy-scoped. Inventory movements allow insert/read but not update/delete for the API role.

The migration also allows pharmacy members to see active supplier organizations so the live supplier directory can load. This does not grant access to supplier memberships or private stock. Service authorization remains required even when RLS is enabled.

`DATABASE_URL_RLS` is preferred for request traffic. The `pharma_api` role created by the identity migration is `NOLOGIN`; provision a dedicated login and grant it that role, or use an equivalent restricted role with `rolbypassrls = false`. Do not use a Postgres superuser or Supabase service-role connection for API requests. A privileged connection is required only to apply migrations and seed demo data.

## Apply and seed

Apply migrations in timestamp order using the Supabase SQL editor or a database-owner migration connection:

1. `supabase/migrations/20241007120000_phase1_identity.sql`
2. `supabase/migrations/20261007130000_procurement.sql`

The repository uses forward-only SQL migrations and has no down-migration framework. The procurement migration has not been applied in this checkout because no database connection is configured.

To seed real persisted demo records, first create/sign up a Supabase Auth user. From `apps/api`, set the following in the operator's shell and run `python -m app.seed_demo`:

* `SEED_DATABASE_URL`: privileged PostgreSQL URL, used only by this seed command.
* `DEMO_USER_EMAIL`: email of the existing Supabase Auth user to receive pharmacy-admin and supplier-admin demo memberships.

The script is idempotent: it creates a demo pharmacy, supplier, three products, supplier batches, and a pending purchase order if they do not already exist. It does not delete or overwrite existing catalog, stock, or order data. Keep `SEED_DATABASE_URL` out of `apps/web` and browser variables.

## Verification status

The API and frontend unit suites run without a database. This checkout has no `DATABASE_URL`, `DATABASE_URL_RLS`, Supabase URL, or Supabase public key configured. Migration execution, live RLS/constraint behavior, seed execution, and HTTP-to-database persistence therefore still require a configured Supabase/PostgreSQL project.
