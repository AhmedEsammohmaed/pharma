# PharmaIntelligence

PharmaIntelligence is a pharmacy operations application with a Next.js / TypeScript frontend and a FastAPI / SQLAlchemy backend. Supabase Auth provides login; PostgreSQL is the source of truth for identity, supplier inventory, purchase orders, pharmacy batches, and inventory movements.

## Start the web app

```powershell
cd apps/web
pnpm install
pnpm dev
```

Open [http://localhost:3000](http://localhost:3000). Copy the web settings from `.env.example` to `apps/web/.env.local`.

## Start the API

```powershell
cd apps/api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
```

Copy `.env.example` to `apps/api/.env`, configure Supabase Auth and PostgreSQL, and apply SQL migrations in timestamp order before using procurement routes. `/health/ready` checks an actual database connection.

## Apply migrations and seed a database

Apply these SQL files with the Supabase SQL editor or a database-owner migration connection, in order:

1. `supabase/migrations/20241007120000_phase1_identity.sql`
2. `supabase/migrations/20261007130000_procurement.sql`

Create or sign up a Supabase Auth demo user. Then run this from `apps/api` in an operator shell with a privileged database URL:

```powershell
$env:SEED_DATABASE_URL = "<privileged PostgreSQL URL>"
$env:DEMO_USER_EMAIL = "<existing Supabase Auth user email>"
python -m app.seed_demo
```

The seed is idempotent. It creates a demo pharmacy and supplier, catalog products, real supplier inventory batches, and a pending purchase order with persisted line items. The selected user receives pharmacy-admin and supplier-admin memberships. Use a disposable development project for this demo user. `SEED_DATABASE_URL` is server/operator-only and must never be copied into frontend configuration.

## Procurement behavior

The **Suppliers** section shows supplier stock from the API. Supplier members can add, update, and remove batches. Pharmacy members can create purchase orders from current supplier offers. Suppliers confirm orders, progress them through processing/ready/shipped, and pharmacy members receive cumulative shipment quantities. Receipt creates pharmacy batch records and append-only inventory movement entries atomically. See [API.md](API.md) and [DATABASE.md](DATABASE.md) for endpoints, roles, RLS, and the order lifecycle.

## Tests

```powershell
cd apps/api
.\.venv\Scripts\python.exe -m pytest -q

cd ..\web
pnpm exec tsc --noEmit
pnpm test
pnpm build
```

The current checkout has no configured PostgreSQL or Supabase URL. Unit/API and UI tests can run locally, but applying the migration, seeding rows, testing database/RLS constraints, and verifying persistence across browser refresh require connecting a Supabase/PostgreSQL project. The UI shows an explicit API/database error and does not fall back to local or demo records for the procurement sections.

Overview, analytics, report exports, and Copilot still contain clearly labeled sample UI data. They are not returned by the procurement API.
