import { apiUrl } from "@/lib/env";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

type ErrorBody = { error?: { code?: string; message?: string; details?: unknown } };

function validationMessage(details: unknown): string | null {
  if (!Array.isArray(details)) return null;
  const issues = details.flatMap((entry) => {
    if (typeof entry !== "object" || entry === null) return [];
    const issue = entry as { location?: unknown; message?: unknown };
    if (typeof issue.message !== "string") return [];
    const location = Array.isArray(issue.location)
      ? issue.location.filter((part) => part !== "body").join(".")
      : "";
    return [`${location ? `${location}: ` : ""}${issue.message}`];
  });
  return issues.length ? issues.join("; ") : null;
}

export async function apiFetch<T>(
  path: string,
  accessToken: string,
  init: RequestInit & { organizationId?: string } = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${accessToken}`);
  headers.set("Content-Type", "application/json");
  if (init.organizationId) {
    headers.set("X-Organization-Id", init.organizationId);
  }
  const { organizationId: _ignored, ...rest } = init;
  const response = await fetch(`${apiUrl}${path}`, { ...rest, headers });
  if (!response.ok) {
    let code = "http_error";
    let message = `Request failed (${response.status})`;
    try {
      const body = (await response.json()) as ErrorBody;
      code = body.error?.code ?? code;
      message = body.error?.message ?? message;
      if (response.status === 422) {
        const fields = validationMessage(body.error?.details);
        if (fields) message = `${message}: ${fields}`;
      }
    } catch {
      /* empty */
    }
    throw new ApiError(response.status, code, message);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export type Membership = {
  organization_id: string;
  organization_name: string;
  organization_slug: string;
  organization_type: "pharmacy" | "supplier" | "platform";
  role: string;
  status: string;
  permissions: string[];
};

export type Profile = {
  user_id: string;
  email: string | null;
  full_name: string;
  phone: string | null;
  account_kind: string;
  memberships: Membership[];
};

export type Organization = {
  id: string;
  name: string;
  slug: string;
  type: string;
  status: string;
};

export type Member = {
  user_id: string;
  full_name: string;
  role: string;
  status: string;
};

export type AuditRow = {
  id: string;
  action: string;
  resource_type: string;
  resource_id: string | null;
  result: string;
  created_at: string;
};

export type InviteCreated = {
  code: string;
  role: string;
  expires_at: string;
  join_hint: string;
};

export type Product = {
  id: string;
  sku: string;
  name: string;
  generic_name: string | null;
  strength: string | null;
  dosage_form: string | null;
  unit: string;
  category: string | null;
};

export type Supplier = {
  id: string;
  name: string;
  slug: string;
  lead_time_days: number;
  listed_products: number;
};

export type SupplierInventoryItem = {
  id: string;
  supplier_id: string;
  supplier_name: string;
  supplier_product_id: string;
  product_id: string;
  product_name: string;
  product_sku: string;
  unit: string;
  supplier_sku: string | null;
  batch_number: string | null;
  available_quantity: number;
  wholesale_price: string;
  minimum_order_quantity: number;
  lead_time_days: number;
  expiration_date: string | null;
  status: "available" | "unavailable";
  updated_at: string;
};

export type OrderStatus =
  | "PENDING"
  | "CONFIRMED"
  | "PROCESSING"
  | "READY"
  | "SHIPPED"
  | "DELIVERED"
  | "CANCELLED"
  | "RETURNED";

export type PurchaseOrderItem = {
  id: string;
  product_id: string;
  product_name: string;
  product_sku: string;
  supplier_inventory_id: string;
  batch_number: string | null;
  quantity: number;
  received_quantity: number;
  unit_price: string;
  line_total: string;
};

export type PurchaseOrder = {
  id: string;
  organization_id: string;
  supplier_id: string;
  supplier_name: string;
  order_number: string;
  status: OrderStatus;
  subtotal: string;
  tax_total: string;
  total: string;
  notes: string | null;
  created_at: string;
  updated_at: string;
  items: PurchaseOrderItem[];
};

export type PharmacyInventoryBatch = {
  id: string;
  product_id: string;
  product_name: string;
  product_sku: string;
  batch_number: string | null;
  expiration_date: string | null;
  quantity_on_hand: number;
  unit_cost: string;
  supplier_id: string;
  purchase_order_item_id: string;
  updated_at: string;
};

export type InventoryMovement = {
  id: string;
  product_id: string;
  inventory_batch_id: string;
  purchase_order_item_id: string;
  movement_type: "receipt" | "return" | "adjustment";
  quantity_delta: number;
  unit_cost: string;
  actor_user_id: string;
  created_at: string;
};
