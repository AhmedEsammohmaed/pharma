import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ProcurementWorkspace from "@/components/procurement-workspace";
import { ApiError, apiFetch, type Membership, type PurchaseOrder, type SupplierInventoryItem } from "@/lib/api";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, apiFetch: vi.fn() };
});

const pharmacy: Membership = {
  organization_id: "pharmacy-1",
  organization_name: "Demo Pharmacy",
  organization_slug: "demo-pharmacy",
  organization_type: "pharmacy",
  role: "pharmacy_admin",
  status: "active",
  permissions: [],
};
const supplier: Membership = {
  ...pharmacy,
  organization_id: "supplier-1",
  organization_name: "Demo Supplier",
  organization_slug: "demo-supplier",
  organization_type: "supplier",
  role: "supplier_admin",
};

const supply: SupplierInventoryItem = {
  id: "stock-1",
  supplier_id: supplier.organization_id,
  supplier_name: supplier.organization_name,
  supplier_product_id: "supplier-product-1",
  product_id: "product-1",
  product_name: "Paracetamol 500 mg",
  product_sku: "DEMO-PAR-500",
  unit: "tablet",
  supplier_sku: "PAR-500-A",
  batch_number: "BATCH-1",
  available_quantity: 80,
  wholesale_price: "42.50",
  minimum_order_quantity: 5,
  lead_time_days: 3,
  expiration_date: "2027-10-07",
  status: "available",
  updated_at: "2026-10-07T10:00:00Z",
};

const order: PurchaseOrder = {
  id: "order-1",
  organization_id: pharmacy.organization_id,
  supplier_id: supplier.organization_id,
  supplier_name: supplier.organization_name,
  order_number: "PO-TEST-0001",
  status: "PENDING",
  subtotal: "212.50",
  tax_total: "0.00",
  total: "212.50",
  notes: null,
  created_at: "2026-10-07T10:00:00Z",
  updated_at: "2026-10-07T10:00:00Z",
  items: [
    {
      id: "order-item-1",
      product_id: supply.product_id,
      product_name: supply.product_name,
      product_sku: supply.product_sku,
      supplier_inventory_id: supply.id,
      batch_number: supply.batch_number,
      quantity: 5,
      received_quantity: 0,
      unit_price: "42.50",
      line_total: "212.50",
    },
  ],
};

function renderWorkspace(section: "Orders" | "Suppliers", membership: Membership) {
  return render(
    <ProcurementWorkspace
      section={section}
      authStatus="ready"
      accessToken="test-token"
      membership={membership}
      search=""
    />,
  );
}

function mockedApi() {
  return vi.mocked(apiFetch);
}

describe("database-backed procurement workflows", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(cleanup);

  it("creates an order through the API and reloads the saved order", async () => {
    const api = mockedApi();
    api.mockImplementation(async (path, _token, init = {}) => {
      if (path === "/api/v1/orders" && init.method === "POST") return order;
      if (path === "/api/v1/orders") return [order];
      if (path === "/api/v1/suppliers") return [{ id: supplier.organization_id, name: supplier.organization_name, slug: supplier.organization_slug, lead_time_days: 3, listed_products: 1 }];
      if (path === `/api/v1/suppliers/${supplier.organization_id}/inventory`) return [supply];
      throw new Error(`Unexpected API call: ${path}`);
    });

    renderWorkspace("Orders", pharmacy);
    const user = userEvent.setup();
    await screen.findByText("Records loaded from the procurement API");
    await user.click(screen.getByRole("button", { name: /new order/i }));
    await user.selectOptions(screen.getByLabelText("Supplier"), supplier.organization_id);
    await screen.findByRole("option", { name: /Paracetamol 500 mg/ });
    await user.selectOptions(screen.getByLabelText("Product and batch"), supply.id);
    await user.clear(screen.getByLabelText("Quantity"));
    await user.type(screen.getByLabelText("Quantity"), "5");
    await user.click(screen.getByRole("button", { name: "Save purchase order" }));

    expect(await screen.findByText("PO-TEST-0001 was created and saved.")).toBeTruthy();
    await waitFor(() => expect(api).toHaveBeenCalledWith(
      "/api/v1/orders",
      "test-token",
      expect.objectContaining({
        method: "POST",
        organizationId: pharmacy.organization_id,
        body: JSON.stringify({ supplier_id: supplier.organization_id, items: [{ supplier_inventory_id: supply.id, quantity: 5 }], notes: null }),
      }),
    ));
    expect(await screen.findByText("PO-TEST-0001")).toBeTruthy();
  });

  it("shows an authorization error returned by the order API", async () => {
    const api = mockedApi();
    api.mockImplementation(async (path, _token, init = {}) => {
      if (path === "/api/v1/orders" && init.method === "POST") {
        throw new ApiError(403, "forbidden", "You do not have permission to perform this action");
      }
      if (path === "/api/v1/orders") return [];
      if (path === "/api/v1/suppliers") return [{ id: supplier.organization_id, name: supplier.organization_name, slug: supplier.organization_slug, lead_time_days: 3, listed_products: 1 }];
      if (path === `/api/v1/suppliers/${supplier.organization_id}/inventory`) return [supply];
      throw new Error(`Unexpected API call: ${path}`);
    });

    renderWorkspace("Orders", pharmacy);
    const user = userEvent.setup();
    await screen.findByText("Records loaded from the procurement API");
    await user.click(screen.getByRole("button", { name: /new order/i }));
    await user.selectOptions(screen.getByLabelText("Supplier"), supplier.organization_id);
    await screen.findByRole("option", { name: /Paracetamol 500 mg/ });
    await user.selectOptions(screen.getByLabelText("Product and batch"), supply.id);
    await user.clear(screen.getByLabelText("Quantity"));
    await user.type(screen.getByLabelText("Quantity"), "5");
    await user.click(screen.getByRole("button", { name: "Save purchase order" }));

    expect((await screen.findByRole("alert")).textContent).toContain("does not have permission");
  });

  it("keeps the order form open and shows backend validation feedback", async () => {
    const api = mockedApi();
    api.mockImplementation(async (path, _token, init = {}) => {
      if (path === "/api/v1/orders" && init.method === "POST") {
        throw new ApiError(422, "below_minimum_order_quantity", "Order quantity must meet the supplier minimum");
      }
      if (path === "/api/v1/orders") return [];
      if (path === "/api/v1/suppliers") return [{ id: supplier.organization_id, name: supplier.organization_name, slug: supplier.organization_slug, lead_time_days: 3, listed_products: 1 }];
      if (path === `/api/v1/suppliers/${supplier.organization_id}/inventory`) return [supply];
      throw new Error(`Unexpected API call: ${path}`);
    });

    renderWorkspace("Orders", pharmacy);
    const user = userEvent.setup();
    await screen.findByText("Records loaded from the procurement API");
    await user.click(screen.getByRole("button", { name: /new order/i }));
    await user.selectOptions(screen.getByLabelText("Supplier"), supplier.organization_id);
    await screen.findByRole("option", { name: /Paracetamol 500 mg/ });
    await user.selectOptions(screen.getByLabelText("Product and batch"), supply.id);
    await user.clear(screen.getByLabelText("Quantity"));
    await user.type(screen.getByLabelText("Quantity"), "5");
    await user.click(screen.getByRole("button", { name: "Save purchase order" }));

    expect((await screen.findByRole("alert")).textContent).toContain("supplier minimum");
    expect(screen.getByRole("dialog")).toBeTruthy();
  });

  it("shows submission loading and prevents duplicate order requests", async () => {
    const api = mockedApi();
    let finishCreate: ((value: PurchaseOrder) => void) | undefined;
    api.mockImplementation(async (path, _token, init = {}) => {
      if (path === "/api/v1/orders" && init.method === "POST") {
        return await new Promise<PurchaseOrder>((resolve) => { finishCreate = resolve; });
      }
      if (path === "/api/v1/orders") return [];
      if (path === "/api/v1/suppliers") return [{ id: supplier.organization_id, name: supplier.organization_name, slug: supplier.organization_slug, lead_time_days: 3, listed_products: 1 }];
      if (path === `/api/v1/suppliers/${supplier.organization_id}/inventory`) return [supply];
      throw new Error(`Unexpected API call: ${path}`);
    });

    renderWorkspace("Orders", pharmacy);
    const user = userEvent.setup();
    await screen.findByText("Records loaded from the procurement API");
    await user.click(screen.getByRole("button", { name: /new order/i }));
    await user.selectOptions(screen.getByLabelText("Supplier"), supplier.organization_id);
    await screen.findByRole("option", { name: /Paracetamol 500 mg/ });
    await user.selectOptions(screen.getByLabelText("Product and batch"), supply.id);
    await user.clear(screen.getByLabelText("Quantity"));
    await user.type(screen.getByLabelText("Quantity"), "5");
    await user.click(screen.getByRole("button", { name: "Save purchase order" }));

    const pending = await screen.findByRole("button", { name: "Saving order…" });
    expect(pending.hasAttribute("disabled")).toBe(true);
    await user.click(pending);
    expect(api.mock.calls.filter(([path, , init]) => path === "/api/v1/orders" && init?.method === "POST")).toHaveLength(1);
    finishCreate?.(order);
    expect(await screen.findByText("PO-TEST-0001 was created and saved.")).toBeTruthy();
  });

  it("creates supplier stock from the product catalog and refreshes the saved inventory", async () => {
    const api = mockedApi();
    const savedSupply = { ...supply, id: "stock-created", batch_number: "NEW-BATCH", available_quantity: 24, wholesale_price: "20.50" };
    api.mockImplementation(async (path, _token, init = {}) => {
      if (path === `/api/v1/suppliers/${supplier.organization_id}/inventory` && init.method === "POST") return savedSupply;
      if (path === `/api/v1/suppliers/${supplier.organization_id}/inventory`) return [savedSupply];
      if (path === "/api/v1/products") return [{ id: supply.product_id, name: supply.product_name, sku: supply.product_sku, unit: supply.unit }];
      throw new Error(`Unexpected API call: ${path}`);
    });

    renderWorkspace("Suppliers", supplier);
    const user = userEvent.setup();
    await screen.findByRole("heading", { name: "Supplier inventory" });
    await waitFor(() => expect(screen.getByRole("button", { name: /add supply/i }).hasAttribute("disabled")).toBe(false));
    await user.click(screen.getByRole("button", { name: /add supply/i }));
    await user.type(screen.getByLabelText("Batch number"), "NEW-BATCH");
    await user.clear(screen.getByLabelText("Available quantity"));
    await user.type(screen.getByLabelText("Available quantity"), "24");
    await user.clear(screen.getByLabelText("Wholesale unit price (EGP)"));
    await user.type(screen.getByLabelText("Wholesale unit price (EGP)"), "20.50");
    await user.click(screen.getByRole("button", { name: "Add supply" }));

    expect(await screen.findByText("Supply was added and saved.")).toBeTruthy();
    await waitFor(() => expect(api).toHaveBeenCalledWith(
      `/api/v1/suppliers/${supplier.organization_id}/inventory`,
      "test-token",
      expect.objectContaining({
        method: "POST",
        organizationId: supplier.organization_id,
        body: JSON.stringify({
          product_id: supply.product_id,
          supplier_sku: null,
          batch_number: "NEW-BATCH",
          available_quantity: 24,
          wholesale_price: "20.5",
          minimum_order_quantity: 1,
          lead_time_days: 0,
          expiration_date: null,
        }),
      }),
    ));
    expect(await screen.findByText("NEW-BATCH")).toBeTruthy();
  });
});
