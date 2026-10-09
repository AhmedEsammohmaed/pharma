# API Contract

## Authentication and organization context

The FastAPI service uses `/api/v1`; OpenAPI JSON is at `/api/openapi.json` and Swagger UI at `/api/docs`. Protected requests require a Supabase access token:

```http
Authorization: Bearer <access-token>
X-Organization-Id: <organization-uuid>
```

Procurement endpoints require `X-Organization-Id`. The API resolves the user, active membership, organization type, and role from the verified token and database. The header selects a context; it does not prove access. Queries are scoped by that membership and PostgreSQL RLS.

## Health and identity

Health paths are `/health`, `/health/live`, and `/health/ready`. Identity routes include `/api/v1/me`, `/api/v1/organizations`, `/api/v1/organizations/{organization_id}`, members, invites, and audit logs. Their full contract is implemented by the identity module.

## Products and suppliers

| Method | Path | Authorization | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/v1/products` | Pharmacy/supplier member with `products.read` | Read active shared catalog products. |
| `GET` | `/api/v1/suppliers` | Pharmacy or supplier member with `supplier_inventory.read` | Pharmacy sees suppliers with sellable offers; supplier sees its own directory entry. |
| `GET` | `/api/v1/suppliers/{supplier_id}/inventory` | Pharmacy member or the named supplier member | Pharmacy sees sellable, non-expired offers; supplier sees its own non-deleted batches. |
| `POST` | `/api/v1/suppliers/{supplier_id}/inventory` | Named supplier with `supplier_inventory.manage` | Create supplier product relationship and batch. |
| `PATCH` | `/api/v1/suppliers/{supplier_id}/inventory/{inventory_id}` | Named supplier with `supplier_inventory.manage` | Update supplier SKU/lead time or batch values. |
| `DELETE` | `/api/v1/suppliers/{supplier_id}/inventory/{inventory_id}` | Named supplier with `supplier_inventory.manage` | Soft-delete a batch; reserved batches cannot be removed. |

Supplier IDs and product IDs are validated against database records and the authenticated organization. Pharmacy users cannot modify supplier stock. Supplier stock quantities and prices are never taken from a pharmacy order payload.

## Purchase orders and stock receipt

| Method | Path | Authorization | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/v1/orders` | Organization member with `purchase_orders.read` | List only pharmacy-owned or supplier-addressed orders. |
| `POST` | `/api/v1/orders` | Pharmacy member with `purchase_orders.create` | Create an order from available supplier batches; server snapshots prices and calculates totals. |
| `GET` | `/api/v1/orders/{order_id}` | Pharmacy or addressed supplier with `purchase_orders.read` | Read one scoped order. |
| `PATCH` | `/api/v1/orders/{order_id}` | Pharmacy admin with `purchase_orders.manage` | Update notes while the order is pending. |
| `POST` | `/api/v1/orders/{order_id}/status` | Role appropriate to requested transition | Apply one allowed lifecycle transition. Body: `{"status":"PROCESSING"}`. |
| `POST` | `/api/v1/orders/{order_id}/confirm` | Addressed supplier with `purchase_orders.fulfill` | Confirm and reserve supplier stock atomically. |
| `POST` | `/api/v1/orders/{order_id}/cancel` | Pharmacy admin or addressed supplier with `purchase_orders.manage` / `purchase_orders.fulfill` | Cancel an eligible order and release its reservation. |
| `POST` | `/api/v1/orders/{order_id}/receive` | Pharmacy member with `inventory.receive` | Receive cumulative per-line quantities into pharmacy batches and movement ledger. |
| `GET` | `/api/v1/inventory/batches` | Pharmacy member with `inventory.receive` | Read pharmacy stock batches. |
| `GET` | `/api/v1/inventory/movements` | Pharmacy member with `inventory.receive` | Read append-only inventory movements. |

The lifecycle is `PENDING → CONFIRMED → PROCESSING → READY → SHIPPED → DELIVERED`, with cancellation allowed before shipment and `SHIPPED → RETURNED`. Only the receive endpoint can complete delivery. A full receipt sets `DELIVERED`; partial receipt remains `SHIPPED`. See [DATABASE.md](DATABASE.md) for the full transition table and reservation behavior.

For receiving, send every order item exactly once with its cumulative received quantity:

```json
{
  "items": [
    {"item_id": "<purchase-order-item-uuid>", "received_quantity": 12}
  ]
}
```

The order row is locked during receipt. Only the increase from the previously recorded cumulative quantity creates a stock movement, so retries are safe. Batch, movement, item, order status, and audit writes commit in one request transaction.

## Validation, errors, and calculations

Pydantic request models reject malformed IDs, duplicate batch/line entries, non-positive order quantities, invalid prices, invalid expiry dates, and invalid cumulative received quantities. Product and supplier references are checked in the service layer. Order totals are calculated from database prices using decimal arithmetic; tax is currently zero because no tax rules are configured.

Errors use this envelope:

```json
{"error":{"code":"unauthenticated","message":"Missing bearer token","details":null,"request_id":"<uuid>"}}
```

Expected status codes include `401` unauthenticated, `403` insufficient permission, `404` absent or out-of-scope resource, `409` conflicting state/stock, `422` invalid request, and `503` database not configured/unavailable. Unexpected server errors return a safe message; technical details stay in server logs. Successful responses include `X-Request-Id`.

## Live-data boundary

Orders, supplier inventory, pharmacy stock batches, and movements are fetched through these APIs. Overview/analytics figures, report exports, and Copilot conversation remain explicitly identified sample UI data; they are not part of these endpoints.
