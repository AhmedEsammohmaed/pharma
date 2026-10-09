"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import { ApiError, apiFetch, type InventoryMovement, type Membership, type PharmacyInventoryBatch, type PurchaseOrder, type Supplier, type SupplierInventoryItem } from "@/lib/api";

type Section = "Inventory" | "Orders" | "Suppliers";
type AuthStatus = "checking" | "ready" | "signed_out" | "unconfigured" | "error";
type Props = {
  section: Section;
  authStatus: AuthStatus;
  accessToken: string | null;
  membership: Membership | null;
  search: string;
};
type OrderDraftLine = { supplier_inventory_id: string; quantity: string };
type SupplyDraft = {
  product_id: string;
  supplier_sku: string;
  batch_number: string;
  available_quantity: string;
  wholesale_price: string;
  minimum_order_quantity: string;
  lead_time_days: string;
  expiration_date: string;
};

const emptySupply: SupplyDraft = {
  product_id: "",
  supplier_sku: "",
  batch_number: "",
  available_quantity: "",
  wholesale_price: "",
  minimum_order_quantity: "1",
  lead_time_days: "0",
  expiration_date: "",
};

function apiMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return "Your session expired. Sign in again to continue.";
    if (error.status === 403) return "Your account does not have permission to perform this action.";
    if (error.status === 404) return "The requested record is no longer available in this organization.";
    if (error.status === 409) return error.message;
    if (error.status === 422) return error.message || "Check the submitted values and try again.";
    return error.message;
  }
  return "Could not reach the API. Check that the backend is running and try again.";
}

function money(value: string | number): string {
  return new Intl.NumberFormat("en-EG", { style: "currency", currency: "EGP", maximumFractionDigits: 2 }).format(Number(value));
}

function dateLabel(value: string | null): string {
  if (!value) return "No expiry date";
  return new Intl.DateTimeFormat("en-EG", { dateStyle: "medium" }).format(new Date(`${value}T00:00:00`));
}

function statusClass(status: string): string {
  const normalized = status.toLowerCase();
  if (["cancelled", "returned"].includes(normalized)) return "status-pill status-cancelled";
  if (["pending", "confirmed", "processing", "ready"].includes(normalized)) return "status-pill status-processing";
  return "status-pill status-completed";
}

function AccessNotice({ status }: { status: AuthStatus }) {
  if (status === "checking") return <div className="data-state" role="status">Checking your session…</div>;
  if (status === "unconfigured") {
    return <div className="data-state data-state-error" role="alert">Supabase is not configured. Set the web environment variables to load live records.</div>;
  }
  if (status === "error") return <div className="data-state data-state-error" role="alert">Could not load your profile from the API. Check the Supabase and database configuration, then refresh.</div>;
  return <div className="data-state">Sign in to load persisted orders and supplier inventory. <Link href="/login">Sign in</Link></div>;
}

function EmptyState({ children }: { children: React.ReactNode }) {
  return <div className="data-state">{children}</div>;
}

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="procurement-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="procurement-modal" role="dialog" aria-modal="true" aria-labelledby="procurement-modal-title">
        <div className="procurement-modal-heading"><div><p className="eyebrow">DATABASE-BACKED WORKFLOW</p><h2 id="procurement-modal-title">{title}</h2></div><button className="icon-button" type="button" onClick={onClose} aria-label="Close dialog">×</button></div>
        {children}
      </section>
    </div>
  );
}

export default function ProcurementWorkspace({ section, authStatus, accessToken, membership, search }: Props) {
  const [orders, setOrders] = useState<PurchaseOrder[]>([]);
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [inventory, setInventory] = useState<SupplierInventoryItem[]>([]);
  const [pharmacyInventory, setPharmacyInventory] = useState<PharmacyInventoryBatch[]>([]);
  const [movements, setMovements] = useState<InventoryMovement[]>([]);
  const [products, setProducts] = useState<Array<{ id: string; name: string; sku: string; unit: string }>>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [success, setSuccess] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [showOrderForm, setShowOrderForm] = useState(false);
  const [orderPending, setOrderPending] = useState(false);
  const [orderError, setOrderError] = useState("");
  const [orderSupplierId, setOrderSupplierId] = useState("");
  const [orderInventory, setOrderInventory] = useState<SupplierInventoryItem[]>([]);
  const [orderInventoryLoading, setOrderInventoryLoading] = useState(false);
  const [orderLines, setOrderLines] = useState<OrderDraftLine[]>([{ supplier_inventory_id: "", quantity: "1" }]);
  const [orderNotes, setOrderNotes] = useState("");
  const [receivingOrder, setReceivingOrder] = useState<PurchaseOrder | null>(null);
  const [receivedQuantities, setReceivedQuantities] = useState<Record<string, string>>({});
  const [receivePending, setReceivePending] = useState(false);
  const [receiveError, setReceiveError] = useState("");
  const [showSupplyForm, setShowSupplyForm] = useState(false);
  const [editingSupply, setEditingSupply] = useState<SupplierInventoryItem | null>(null);
  const [supplyDraft, setSupplyDraft] = useState<SupplyDraft>(emptySupply);
  const [supplyPending, setSupplyPending] = useState(false);
  const [supplyError, setSupplyError] = useState("");
  const organizationId = membership?.organization_id ?? "";
  const organizationType = membership?.organization_type;
  const supplierMode = organizationType === "supplier";
  const pharmacyMode = organizationType === "pharmacy";

  const loadData = useCallback(async () => {
    if (authStatus !== "ready" || !accessToken || !organizationId || !membership) return;
    setLoading(true);
    setLoadError("");
    try {
      if (section === "Orders") {
        const result = await apiFetch<PurchaseOrder[]>("/api/v1/orders", accessToken, { organizationId });
        setOrders(result);
        if (pharmacyMode) {
          setSuppliers(await apiFetch<Supplier[]>("/api/v1/suppliers", accessToken, { organizationId }));
        }
      } else if (section === "Suppliers") {
        if (pharmacyMode) {
          setSuppliers(await apiFetch<Supplier[]>("/api/v1/suppliers", accessToken, { organizationId }));
        } else if (supplierMode) {
          const [ownInventory, productCatalog] = await Promise.all([
            apiFetch<SupplierInventoryItem[]>(`/api/v1/suppliers/${organizationId}/inventory`, accessToken, { organizationId }),
            apiFetch<Array<{ id: string; name: string; sku: string; unit: string }>>("/api/v1/products", accessToken, { organizationId }),
          ]);
          setInventory(ownInventory);
          setProducts(productCatalog);
        }
      } else if (section === "Inventory" && pharmacyMode) {
        const [batches, ledger] = await Promise.all([
          apiFetch<PharmacyInventoryBatch[]>("/api/v1/inventory/batches", accessToken, { organizationId }),
          apiFetch<InventoryMovement[]>("/api/v1/inventory/movements", accessToken, { organizationId }),
        ]);
        setPharmacyInventory(batches);
        setMovements(ledger);
      }
    } catch (error) {
      setLoadError(apiMessage(error));
    } finally {
      setLoading(false);
    }
  }, [accessToken, authStatus, organizationId, membership, pharmacyMode, section, supplierMode]);

  useEffect(() => { void loadData(); }, [loadData, refresh]);

  useEffect(() => {
    let cancelled = false;
    async function loadSelectedSupplier() {
      if (!showOrderForm || !orderSupplierId || !accessToken || !organizationId) {
        setOrderInventory([]);
        return;
      }
      setOrderInventoryLoading(true);
      setOrderError("");
      try {
        const rows = await apiFetch<SupplierInventoryItem[]>(
          `/api/v1/suppliers/${orderSupplierId}/inventory`,
          accessToken,
          { organizationId },
        );
        if (!cancelled) setOrderInventory(rows);
      } catch (error) {
        if (!cancelled) setOrderError(apiMessage(error));
      } finally {
        if (!cancelled) setOrderInventoryLoading(false);
      }
    }
    void loadSelectedSupplier();
    return () => { cancelled = true; };
  }, [accessToken, organizationId, orderSupplierId, showOrderForm]);

  const visibleOrders = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return orders;
    return orders.filter((order) =>
      `${order.order_number} ${order.supplier_name} ${order.status} ${order.items.map((item) => item.product_name).join(" ")}`
        .toLowerCase().includes(needle),
    );
  }, [orders, search]);

  const visibleInventory = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return inventory;
    return inventory.filter((item) => `${item.product_name} ${item.product_sku} ${item.batch_number ?? ""}`.toLowerCase().includes(needle));
  }, [inventory, search]);

  const visiblePharmacyInventory = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return pharmacyInventory;
    return pharmacyInventory.filter((item) => `${item.product_name} ${item.product_sku} ${item.batch_number ?? ""}`.toLowerCase().includes(needle));
  }, [pharmacyInventory, search]);

  function openOrderForm(supplierId = "") {
    setOrderSupplierId(supplierId);
    setOrderLines([{ supplier_inventory_id: "", quantity: "1" }]);
    setOrderNotes("");
    setOrderError("");
    setShowOrderForm(true);
  }

  async function submitOrder(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!accessToken || !organizationId) return;
    const selected = orderLines.map((line) => ({
      supplier_inventory_id: line.supplier_inventory_id,
      quantity: Number(line.quantity),
    }));
    const duplicate = new Set(selected.map((item) => item.supplier_inventory_id)).size !== selected.length;
    if (selected.some((item) => !item.supplier_inventory_id || !Number.isInteger(item.quantity) || item.quantity <= 0) || duplicate) {
      setOrderError("Choose a different supplier batch for each line and enter a positive whole-number quantity.");
      return;
    }
    setOrderPending(true);
    setOrderError("");
    try {
      const created = await apiFetch<PurchaseOrder>("/api/v1/orders", accessToken, {
        method: "POST",
        organizationId,
        body: JSON.stringify({ supplier_id: orderSupplierId, items: selected, notes: orderNotes || null }),
      });
      setShowOrderForm(false);
      setSuccess(`${created.order_number} was created and saved.`);
      setRefresh((value) => value + 1);
    } catch (error) {
      setOrderError(apiMessage(error));
    } finally {
      setOrderPending(false);
    }
  }

  async function changeOrderStatus(order: PurchaseOrder, target: PurchaseOrder["status"]) {
    if (!accessToken || !organizationId) return;
    if (target === "CANCELLED" && !window.confirm(`Cancel ${order.order_number}?`)) return;
    if (target === "RETURNED" && !window.confirm(`Mark ${order.order_number} returned? Supplier stock is restored only when no receipt was recorded.`)) return;
    setLoadError("");
    try {
      await apiFetch<PurchaseOrder>(`/api/v1/orders/${order.id}/status`, accessToken, {
        method: "POST",
        organizationId,
        body: JSON.stringify({ status: target }),
      });
      setSuccess(`${order.order_number} is now ${target.toLowerCase()}.`);
      setRefresh((value) => value + 1);
    } catch (error) {
      setLoadError(apiMessage(error));
    }
  }

  async function submitReceipt(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!receivingOrder || !accessToken || !organizationId) return;
    setReceivePending(true);
    setReceiveError("");
    try {
      const result = await apiFetch<PurchaseOrder>(`/api/v1/orders/${receivingOrder.id}/receive`, accessToken, {
        method: "POST",
        organizationId,
        body: JSON.stringify({
          items: receivingOrder.items.map((item) => ({ item_id: item.id, received_quantity: Number(receivedQuantities[item.id] ?? item.received_quantity) })),
        }),
      });
      setReceivingOrder(null);
      setSuccess(`${result.order_number} receipt was saved${result.status === "DELIVERED" ? " and the order is complete" : ""}.`);
      setRefresh((value) => value + 1);
    } catch (error) {
      setReceiveError(apiMessage(error));
    } finally {
      setReceivePending(false);
    }
  }

  function openSupplyCreate() {
    setEditingSupply(null);
    setSupplyDraft({ ...emptySupply, product_id: products[0]?.id ?? "" });
    setSupplyError("");
    setShowSupplyForm(true);
  }

  function openSupplyEdit(item: SupplierInventoryItem) {
    setEditingSupply(item);
    setSupplyDraft({
      product_id: item.product_id,
      supplier_sku: item.supplier_sku ?? "",
      batch_number: item.batch_number ?? "",
      available_quantity: String(item.available_quantity),
      wholesale_price: item.wholesale_price,
      minimum_order_quantity: String(item.minimum_order_quantity),
      lead_time_days: String(item.lead_time_days),
      expiration_date: item.expiration_date ?? "",
    });
    setSupplyError("");
    setShowSupplyForm(true);
  }

  async function submitSupply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!accessToken || !organizationId) return;
    setSupplyPending(true);
    setSupplyError("");
    const endpoint = `/api/v1/suppliers/${organizationId}/inventory`;
    const createPayload = {
      product_id: supplyDraft.product_id,
      supplier_sku: supplyDraft.supplier_sku || null,
      batch_number: supplyDraft.batch_number || null,
      available_quantity: Number(supplyDraft.available_quantity),
      wholesale_price: supplyDraft.wholesale_price,
      minimum_order_quantity: Number(supplyDraft.minimum_order_quantity),
      lead_time_days: Number(supplyDraft.lead_time_days),
      expiration_date: supplyDraft.expiration_date || null,
    };
    const updatePayload = {
      supplier_sku: supplyDraft.supplier_sku || null,
      available_quantity: Number(supplyDraft.available_quantity),
      wholesale_price: supplyDraft.wholesale_price,
      minimum_order_quantity: Number(supplyDraft.minimum_order_quantity),
      lead_time_days: Number(supplyDraft.lead_time_days),
      expiration_date: supplyDraft.expiration_date || null,
    };
    try {
      await apiFetch<SupplierInventoryItem>(
        editingSupply ? `${endpoint}/${editingSupply.id}` : endpoint,
        accessToken,
        {
          method: editingSupply ? "PATCH" : "POST",
          organizationId,
          body: JSON.stringify(editingSupply ? updatePayload : createPayload),
        },
      );
      setShowSupplyForm(false);
      setSuccess(editingSupply ? "Supplier inventory was updated." : "Supply was added and saved.");
      setRefresh((value) => value + 1);
    } catch (error) {
      setSupplyError(apiMessage(error));
    } finally {
      setSupplyPending(false);
    }
  }

  async function removeSupply(item: SupplierInventoryItem) {
    if (!accessToken || !organizationId || !window.confirm(`Remove ${item.product_name}${item.batch_number ? ` · batch ${item.batch_number}` : ""} from active supply?`)) return;
    try {
      await apiFetch<void>(`/api/v1/suppliers/${organizationId}/inventory/${item.id}`, accessToken, { method: "DELETE", organizationId });
      setSuccess("Supply was removed from the active catalog.");
      setRefresh((value) => value + 1);
    } catch (error) {
      setLoadError(apiMessage(error));
    }
  }

  if (authStatus !== "ready") return <AccessNotice status={authStatus} />;
  if (!membership || !organizationId) return <EmptyState>Choose or create a pharmacy or supplier organization before loading records.</EmptyState>;

  const heading = section === "Orders"
    ? supplierMode ? "Incoming purchase orders" : "Purchase orders"
    : section === "Suppliers"
      ? supplierMode ? "Supplier inventory" : "Suppliers"
      : "Pharmacy inventory";
  const description = section === "Orders"
    ? supplierMode ? "Review and fulfil purchase orders sent to your supplier organization." : "Create orders from live supplier stock and follow each delivery."
    : section === "Suppliers"
      ? supplierMode ? "Manage the product batches available to pharmacy customers." : "Browse suppliers with live product availability."
      : "Stock on hand is updated from confirmed shipment receipts.";

  return (
    <>
      <div className="page-heading">
        <div><p className="eyebrow">{section === "Orders" ? "Procurement" : section === "Suppliers" ? "Supplier network" : "Stock control"}</p><h1>{heading}</h1><p className="page-description">{description}</p></div>
        <div className="heading-actions">
          {section === "Orders" && pharmacyMode ? <button className="button-primary" onClick={() => openOrderForm()} type="button">＋ New order</button> : null}
          {section === "Suppliers" && supplierMode ? <button className="button-primary" onClick={openSupplyCreate} type="button">＋ Add supply</button> : null}
          {section === "Suppliers" && pharmacyMode ? <button className="button-primary" onClick={() => openOrderForm()} type="button">＋ New order</button> : null}
        </div>
      </div>

      {success ? <div className="data-alert data-alert-success" role="status"><span>{success}</span><button type="button" onClick={() => setSuccess("")} aria-label="Dismiss success">×</button></div> : null}
      {loadError ? <div className="data-alert data-alert-error" role="alert"><span>{loadError}</span><button type="button" onClick={() => setRefresh((value) => value + 1)}>Retry</button></div> : null}
      {loading ? <div className="data-state" role="status">Loading saved records…</div> : null}

      {!loading && !loadError && section === "Orders" ? (
        <section className="panel table-panel full-table-panel">
          <div className="panel-heading"><div><h2>Purchase orders</h2><p>Records loaded from the procurement API</p></div><span className="live-tag">LIVE DATA</span></div>
          {visibleOrders.length === 0 ? <EmptyState>No purchase orders have been saved for this organization yet.</EmptyState> : (
            <div className="table-scroll"><table><thead><tr><th>ORDER</th><th>SUPPLIER</th><th>ITEMS</th><th>TOTAL</th><th>STATUS</th><th>CREATED</th><th>ACTIONS</th></tr></thead><tbody>
              {visibleOrders.map((order) => <tr key={order.id}>
                <td className="sku-text">{order.order_number}</td>
                <td><strong>{order.supplier_name}</strong></td>
                <td>{order.items.map((item) => `${item.product_name} × ${item.quantity}`).join(", ")}</td>
                <td><strong>{money(order.total)}</strong></td>
                <td><span className={statusClass(order.status)}><i />{order.status}</span></td>
                <td className="date-text">{new Intl.DateTimeFormat("en-EG", { dateStyle: "medium" }).format(new Date(order.created_at))}</td>
                <td><div className="data-actions">
                  {supplierMode && order.status === "PENDING" ? <button className="table-action" onClick={() => void changeOrderStatus(order, "CONFIRMED")}>Confirm</button> : null}
                  {supplierMode && order.status === "CONFIRMED" ? <button className="table-action" onClick={() => void changeOrderStatus(order, "PROCESSING")}>Start</button> : null}
                  {supplierMode && order.status === "PROCESSING" ? <button className="table-action" onClick={() => void changeOrderStatus(order, "READY")}>Mark ready</button> : null}
                  {supplierMode && order.status === "READY" ? <button className="table-action" onClick={() => void changeOrderStatus(order, "SHIPPED")}>Ship</button> : null}
                  {supplierMode && order.status === "SHIPPED" ? <button className="table-action table-action-danger" onClick={() => void changeOrderStatus(order, "RETURNED")}>Mark returned</button> : null}
                  {supplierMode && ["PENDING", "CONFIRMED", "PROCESSING", "READY"].includes(order.status) ? <button className="table-action table-action-danger" onClick={() => void changeOrderStatus(order, "CANCELLED")}>Cancel</button> : null}
                  {pharmacyMode && ["PENDING", "CONFIRMED", "PROCESSING", "READY"].includes(order.status) && membership.role === "pharmacy_admin" ? <button className="table-action table-action-danger" onClick={() => void changeOrderStatus(order, "CANCELLED")}>Cancel</button> : null}
                  {pharmacyMode && order.status === "SHIPPED" ? <button className="table-action" onClick={() => { setReceivingOrder(order); setReceivedQuantities(Object.fromEntries(order.items.map((item) => [item.id, String(item.received_quantity)]))); setReceiveError(""); }}>Receive</button> : null}
                  {!((supplierMode && ["PENDING", "CONFIRMED", "PROCESSING", "READY", "SHIPPED"].includes(order.status)) || (pharmacyMode && (order.status === "SHIPPED" || (["PENDING", "CONFIRMED", "PROCESSING", "READY"].includes(order.status) && membership.role === "pharmacy_admin")))) ? <span className="unit-label">—</span> : null}
                </div></td>
              </tr>)}
            </tbody></table></div>
          )}
          {!loadError && !loading ? <div className="table-foot"><span>Showing {visibleOrders.length} saved orders</span></div> : null}
        </section>
      ) : null}

      {!loading && !loadError && section === "Suppliers" && pharmacyMode ? (
        <section className="panel table-panel full-table-panel">
          <div className="panel-heading"><div><h2>Available suppliers</h2><p>Supplier organizations with active offers</p></div><span className="live-tag">LIVE DATA</span></div>
          {suppliers.length === 0 ? <EmptyState>No suppliers have published available stock yet.</EmptyState> : <div className="supplier-grid">{suppliers.filter((supplier) => `${supplier.name} ${supplier.slug}`.toLowerCase().includes(search.toLowerCase())).map((supplier) => <article className="panel supplier-card" key={supplier.id}>
            <div className="supplier-card-top"><span className="supplier-avatar mint">{supplier.name.slice(0, 2).toUpperCase()}</span><span className="live-tag">ACTIVE</span></div>
            <h2>{supplier.name}</h2><p>{supplier.listed_products} products · {supplier.lead_time_days} day lead time</p>
            <div className="supplier-card-foot"><span className="unit-label">Supplier catalog</span><button className="text-action" type="button" onClick={() => openOrderForm(supplier.id)}>Create order →</button></div>
          </article>)}</div>}
        </section>
      ) : null}

      {!loading && !loadError && section === "Suppliers" && supplierMode ? (
        <section className="panel table-panel full-table-panel">
          <div className="panel-heading"><div><h2>Published supply</h2><p>Supplier product and batch records saved in PostgreSQL</p></div><span className="live-tag">LIVE DATA</span></div>
          {visibleInventory.length === 0 ? <EmptyState>No supplies are published yet. Add a product batch to make it available to pharmacies.</EmptyState> : <div className="table-scroll"><table><thead><tr><th>PRODUCT</th><th>BATCH</th><th>AVAILABLE</th><th>UNIT PRICE</th><th>MIN. ORDER</th><th>EXPIRES</th><th>ACTIONS</th></tr></thead><tbody>
            {visibleInventory.map((item) => <tr key={item.id}><td><div className="product-cell"><span className="product-thumb">{item.product_name.slice(0, 1)}</span><span><strong>{item.product_name}</strong><small>{item.product_sku} · {item.unit}</small></span></div></td><td>{item.batch_number ?? "—"}</td><td><strong>{item.available_quantity}</strong></td><td><strong>{money(item.wholesale_price)}</strong></td><td>{item.minimum_order_quantity}</td><td>{dateLabel(item.expiration_date)}</td><td><div className="data-actions"><button className="table-action" onClick={() => openSupplyEdit(item)}>Edit</button><button className="table-action table-action-danger" onClick={() => void removeSupply(item)}>Remove</button></div></td></tr>)}
          </tbody></table></div>}
        </section>
      ) : null}

      {!loading && !loadError && section === "Inventory" && pharmacyMode ? (
        <>
          <div className="metric-grid compact-metrics">
            <article className="metric-card"><p className="metric-label">Batches on hand</p><div className="metric-value-row"><strong>{pharmacyInventory.length}</strong><span className="metric-note">saved inventory batches</span></div></article>
            <article className="metric-card"><p className="metric-label">Units received</p><div className="metric-value-row"><strong>{pharmacyInventory.reduce((sum, row) => sum + row.quantity_on_hand, 0).toLocaleString()}</strong><span className="metric-note">current on-hand total</span></div></article>
            <article className="metric-card"><p className="metric-label">Products stocked</p><div className="metric-value-row"><strong>{new Set(pharmacyInventory.map((row) => row.product_id)).size}</strong><span className="metric-note">distinct products</span></div></article>
            <article className="metric-card"><p className="metric-label">Movement records</p><div className="metric-value-row"><strong>{movements.length}</strong><span className="metric-note">append-only ledger</span></div></article>
          </div>
          <section className="panel table-panel full-table-panel"><div className="panel-heading"><div><h2>Pharmacy stock</h2><p>Quantities are changed through shipment receipts</p></div><span className="live-tag">LIVE DATA</span></div>
            {visiblePharmacyInventory.length === 0 ? <EmptyState>No stock has been received yet. Receive a shipped purchase order to add pharmacy inventory.</EmptyState> : <div className="table-scroll"><table><thead><tr><th>PRODUCT</th><th>BATCH</th><th>ON HAND</th><th>UNIT COST</th><th>EXPIRATION</th></tr></thead><tbody>
              {visiblePharmacyInventory.map((item) => <tr key={item.id}><td><div className="product-cell"><span className="product-thumb">{item.product_name.slice(0, 1)}</span><span><strong>{item.product_name}</strong><small>{item.product_sku}</small></span></div></td><td>{item.batch_number ?? "—"}</td><td><strong>{item.quantity_on_hand}</strong></td><td>{money(item.unit_cost)}</td><td>{dateLabel(item.expiration_date)}</td></tr>)}
            </tbody></table></div>}
          </section>
          <section className="panel table-panel full-table-panel"><div className="panel-heading"><div><h2>Recent inventory movements</h2><p>Receipts and changes recorded with each transaction</p></div></div>
            {movements.length === 0 ? <EmptyState>Inventory movements will appear here after the first shipment receipt.</EmptyState> : <div className="table-scroll"><table><thead><tr><th>TYPE</th><th>PRODUCT</th><th>QUANTITY CHANGE</th><th>UNIT COST</th><th>RECORDED</th></tr></thead><tbody>
              {movements.map((movement) => <tr key={movement.id}><td>{movement.movement_type}</td><td>{pharmacyInventory.find((batch) => batch.id === movement.inventory_batch_id)?.product_name ?? "Product"}</td><td className="movement-positive">+{movement.quantity_delta}</td><td>{money(movement.unit_cost)}</td><td>{new Intl.DateTimeFormat("en-EG", { dateStyle: "medium", timeStyle: "short" }).format(new Date(movement.created_at))}</td></tr>)}
            </tbody></table></div>}
          </section>
        </>
      ) : null}

      {!loading && !loadError && section === "Inventory" && supplierMode ? <EmptyState>Supplier inventory is managed from the Suppliers section. Pharmacy stock appears only in a pharmacy organization.</EmptyState> : null}

      {showOrderForm ? <Modal title="Create purchase order" onClose={() => { if (!orderPending) setShowOrderForm(false); }}>
        <form className="procurement-form" onSubmit={submitOrder}>
          <label>Supplier<select className="input" required value={orderSupplierId} onChange={(event) => { setOrderSupplierId(event.target.value); setOrderLines([{ supplier_inventory_id: "", quantity: "1" }]); }}><option value="">Choose a supplier</option>{suppliers.map((supplier) => <option key={supplier.id} value={supplier.id}>{supplier.name}</option>)}</select></label>
          {orderInventoryLoading ? <p className="form-hint" role="status">Loading current supplier stock…</p> : null}
          {orderInventory.length === 0 && orderSupplierId && !orderInventoryLoading ? <p className="form-hint">This supplier has no available inventory to order.</p> : null}
          <div className="order-line-heading"><strong>Order items</strong><button className="button-secondary" type="button" onClick={() => setOrderLines((rows) => [...rows, { supplier_inventory_id: "", quantity: "1" }])} disabled={!orderInventory.length}>＋ Add item</button></div>
          {orderLines.map((line, index) => {
            const selected = orderInventory.find((item) => item.id === line.supplier_inventory_id);
            return <div className="order-line" key={index}>
              <label>Product and batch<select className="input" required value={line.supplier_inventory_id} onChange={(event) => setOrderLines((rows) => rows.map((row, rowIndex) => rowIndex === index ? { ...row, supplier_inventory_id: event.target.value } : row))}><option value="">Choose available stock</option>{orderInventory.map((item) => <option key={item.id} value={item.id}>{item.product_name}{item.batch_number ? ` · ${item.batch_number}` : ""} · {money(item.wholesale_price)} · {item.available_quantity} available</option>)}</select>{selected ? <small className="form-hint">Minimum {selected.minimum_order_quantity} {selected.unit}; {selected.available_quantity} available</small> : null}</label>
              <label>Quantity<input className="input" type="number" min={selected?.minimum_order_quantity ?? 1} max={selected?.available_quantity} step="1" required value={line.quantity} onChange={(event) => setOrderLines((rows) => rows.map((row, rowIndex) => rowIndex === index ? { ...row, quantity: event.target.value } : row))} /></label>
              {orderLines.length > 1 ? <button className="remove-line" type="button" aria-label="Remove order line" onClick={() => setOrderLines((rows) => rows.filter((_, rowIndex) => rowIndex !== index))}>×</button> : null}
            </div>;
          })}
          <label>Notes<textarea className="input" rows={3} maxLength={2000} value={orderNotes} onChange={(event) => setOrderNotes(event.target.value)} placeholder="Optional delivery or purchasing notes" /></label>
          {orderError ? <p className="form-error" role="alert">{orderError}</p> : null}
          <div className="form-actions"><button className="button-secondary" type="button" disabled={orderPending} onClick={() => setShowOrderForm(false)}>Close</button><button className="button-primary" type="submit" disabled={orderPending || orderInventoryLoading || !orderSupplierId}>{orderPending ? "Saving order…" : "Save purchase order"}</button></div>
        </form>
      </Modal> : null}

      {receivingOrder ? <Modal title={`Receive ${receivingOrder.order_number}`} onClose={() => { if (!receivePending) setReceivingOrder(null); }}>
        <form className="procurement-form" onSubmit={submitReceipt}>
          <p className="form-hint">Enter the cumulative quantity received for each line. Re-submitting the same quantities will not add stock twice.</p>
          {receivingOrder.items.map((item) => <label key={item.id}>{item.product_name} · ordered {item.quantity}, received {item.received_quantity}<input className="input" type="number" min={item.received_quantity} max={item.quantity} step="1" required value={receivedQuantities[item.id] ?? String(item.received_quantity)} onChange={(event) => setReceivedQuantities((current) => ({ ...current, [item.id]: event.target.value }))} /></label>)}
          {receiveError ? <p className="form-error" role="alert">{receiveError}</p> : null}
          <div className="form-actions"><button className="button-secondary" type="button" disabled={receivePending} onClick={() => setReceivingOrder(null)}>Close</button><button className="button-primary" type="submit" disabled={receivePending}>{receivePending ? "Saving receipt…" : "Save receipt"}</button></div>
        </form>
      </Modal> : null}

      {showSupplyForm ? <Modal title={editingSupply ? "Update supplier supply" : "Add supplier supply"} onClose={() => { if (!supplyPending) setShowSupplyForm(false); }}>
        <form className="procurement-form" onSubmit={submitSupply}>
          <label>Product<select className="input" required disabled={Boolean(editingSupply)} value={supplyDraft.product_id} onChange={(event) => setSupplyDraft((draft) => ({ ...draft, product_id: event.target.value }))}><option value="">Choose a product from the catalog</option>{products.map((product) => <option key={product.id} value={product.id}>{product.name} · {product.sku}</option>)}</select></label>
          <div className="form-grid"><label>Supplier SKU<input className="input" maxLength={100} value={supplyDraft.supplier_sku} onChange={(event) => setSupplyDraft((draft) => ({ ...draft, supplier_sku: event.target.value }))} /></label><label>Batch number<input className="input" maxLength={120} value={supplyDraft.batch_number} onChange={(event) => setSupplyDraft((draft) => ({ ...draft, batch_number: event.target.value }))} /></label></div>
          <div className="form-grid"><label>Available quantity<input className="input" type="number" min="1" step="1" required value={supplyDraft.available_quantity} onChange={(event) => setSupplyDraft((draft) => ({ ...draft, available_quantity: event.target.value }))} /></label><label>Wholesale unit price (EGP)<input className="input" type="number" min="0" step="0.01" required value={supplyDraft.wholesale_price} onChange={(event) => setSupplyDraft((draft) => ({ ...draft, wholesale_price: event.target.value }))} /></label></div>
          <div className="form-grid"><label>Minimum order quantity<input className="input" type="number" min="1" step="1" required value={supplyDraft.minimum_order_quantity} onChange={(event) => setSupplyDraft((draft) => ({ ...draft, minimum_order_quantity: event.target.value }))} /></label><label>Lead time (days)<input className="input" type="number" min="0" max="365" step="1" required value={supplyDraft.lead_time_days} onChange={(event) => setSupplyDraft((draft) => ({ ...draft, lead_time_days: event.target.value }))} /></label></div>
          <label>Expiration date<input className="input" type="date" min={new Date().toISOString().slice(0, 10)} value={supplyDraft.expiration_date} onChange={(event) => setSupplyDraft((draft) => ({ ...draft, expiration_date: event.target.value }))} /></label>
          {products.length === 0 ? <p className="form-hint">No products are available in the catalog. Add products through the catalog seed workflow first.</p> : null}
          {supplyError ? <p className="form-error" role="alert">{supplyError}</p> : null}
          <div className="form-actions"><button className="button-secondary" type="button" disabled={supplyPending} onClick={() => setShowSupplyForm(false)}>Close</button><button className="button-primary" type="submit" disabled={supplyPending || products.length === 0}>{supplyPending ? "Saving supply…" : editingSupply ? "Save changes" : "Add supply"}</button></div>
        </form>
      </Modal> : null}
    </>
  );
}
