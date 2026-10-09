-- PharmaIntelligence procurement, supplier inventory, and pharmacy receiving.
-- Apply after 20241007120000_phase1_identity.sql.

CREATE TABLE IF NOT EXISTS public.products (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  sku text NOT NULL UNIQUE,
  name text NOT NULL,
  generic_name text,
  strength text,
  dosage_form text,
  unit text NOT NULL DEFAULT 'unit',
  category text,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT products_sku_not_blank CHECK (char_length(btrim(sku)) > 0),
  CONSTRAINT products_name_not_blank CHECK (char_length(btrim(name)) > 0),
  CONSTRAINT products_unit_not_blank CHECK (char_length(btrim(unit)) > 0)
);

CREATE INDEX IF NOT EXISTS products_active_name_idx
  ON public.products (name) WHERE active;

CREATE TABLE IF NOT EXISTS public.supplier_products (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  supplier_id uuid NOT NULL REFERENCES public.organizations (id) ON DELETE RESTRICT,
  product_id uuid NOT NULL REFERENCES public.products (id) ON DELETE RESTRICT,
  supplier_sku text,
  lead_time_days integer NOT NULL DEFAULT 0,
  active boolean NOT NULL DEFAULT true,
  created_by uuid NOT NULL REFERENCES auth.users (id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT supplier_products_lead_time_nonnegative CHECK (lead_time_days >= 0),
  CONSTRAINT supplier_products_org_product_unique UNIQUE (supplier_id, product_id),
  CONSTRAINT supplier_products_reference_unique UNIQUE (id, supplier_id, product_id)
);

CREATE INDEX IF NOT EXISTS supplier_products_product_active_idx
  ON public.supplier_products (product_id, supplier_id) WHERE active;

CREATE TABLE IF NOT EXISTS public.supplier_inventory_batches (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  supplier_product_id uuid NOT NULL,
  supplier_id uuid NOT NULL REFERENCES public.organizations (id) ON DELETE RESTRICT,
  product_id uuid NOT NULL REFERENCES public.products (id) ON DELETE RESTRICT,
  batch_number text,
  available_quantity integer NOT NULL,
  reserved_quantity integer NOT NULL DEFAULT 0,
  wholesale_price numeric(12, 2) NOT NULL,
  minimum_order_quantity integer NOT NULL DEFAULT 1,
  expiration_date date,
  status text NOT NULL DEFAULT 'available',
  deleted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT supplier_inventory_supplier_product_fk
    FOREIGN KEY (supplier_product_id, supplier_id, product_id)
    REFERENCES public.supplier_products (id, supplier_id, product_id) ON DELETE RESTRICT,
  CONSTRAINT supplier_inventory_quantity_nonnegative CHECK (available_quantity >= 0),
  CONSTRAINT supplier_inventory_reserved_range CHECK (reserved_quantity >= 0 AND reserved_quantity <= available_quantity),
  CONSTRAINT supplier_inventory_price_nonnegative CHECK (wholesale_price >= 0),
  CONSTRAINT supplier_inventory_moq_positive CHECK (minimum_order_quantity > 0),
  CONSTRAINT supplier_inventory_status_valid CHECK (status IN ('available', 'unavailable')),
  CONSTRAINT supplier_inventory_batch_not_blank CHECK (batch_number IS NULL OR char_length(btrim(batch_number)) > 0),
  CONSTRAINT supplier_inventory_reference_unique UNIQUE (id, supplier_id, product_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS supplier_inventory_unbatched_unique_idx
  ON public.supplier_inventory_batches (supplier_product_id)
  WHERE batch_number IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS supplier_inventory_batch_number_unique_idx
  ON public.supplier_inventory_batches (supplier_product_id, batch_number)
  WHERE batch_number IS NOT NULL;
CREATE INDEX IF NOT EXISTS supplier_inventory_available_idx
  ON public.supplier_inventory_batches (supplier_id, product_id, expiration_date)
  WHERE status = 'available' AND available_quantity > 0;

CREATE TABLE IF NOT EXISTS public.purchase_orders (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES public.organizations (id) ON DELETE RESTRICT,
  supplier_id uuid NOT NULL REFERENCES public.organizations (id) ON DELETE RESTRICT,
  order_number text NOT NULL,
  status text NOT NULL DEFAULT 'PENDING',
  subtotal numeric(12, 2) NOT NULL DEFAULT 0,
  tax_total numeric(12, 2) NOT NULL DEFAULT 0,
  total numeric(12, 2) NOT NULL DEFAULT 0,
  notes text,
  created_by uuid NOT NULL REFERENCES auth.users (id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT purchase_orders_org_order_number_unique UNIQUE (organization_id, order_number),
  CONSTRAINT purchase_orders_reference_unique UNIQUE (id, organization_id, supplier_id),
  CONSTRAINT purchase_orders_number_not_blank CHECK (char_length(btrim(order_number)) > 0),
  CONSTRAINT purchase_orders_status_valid CHECK (status IN (
    'PENDING', 'CONFIRMED', 'PROCESSING', 'READY', 'SHIPPED',
    'DELIVERED', 'CANCELLED', 'RETURNED'
  )),
  CONSTRAINT purchase_orders_totals_nonnegative CHECK (subtotal >= 0 AND tax_total >= 0 AND total >= 0),
  CONSTRAINT purchase_orders_total_matches CHECK (total = subtotal + tax_total)
);

CREATE INDEX IF NOT EXISTS purchase_orders_buyer_recent_idx
  ON public.purchase_orders (organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS purchase_orders_supplier_recent_idx
  ON public.purchase_orders (supplier_id, created_at DESC);
CREATE INDEX IF NOT EXISTS purchase_orders_status_recent_idx
  ON public.purchase_orders (status, created_at DESC);

CREATE TABLE IF NOT EXISTS public.purchase_order_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  purchase_order_id uuid NOT NULL,
  organization_id uuid NOT NULL,
  supplier_id uuid NOT NULL,
  supplier_inventory_id uuid NOT NULL,
  product_id uuid NOT NULL REFERENCES public.products (id) ON DELETE RESTRICT,
  quantity integer NOT NULL,
  received_quantity integer NOT NULL DEFAULT 0,
  unit_price numeric(12, 2) NOT NULL,
  line_total numeric(12, 2) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT purchase_order_items_order_fk
    FOREIGN KEY (purchase_order_id, organization_id, supplier_id)
    REFERENCES public.purchase_orders (id, organization_id, supplier_id) ON DELETE CASCADE,
  CONSTRAINT purchase_order_items_supplier_inventory_fk
    FOREIGN KEY (supplier_inventory_id, supplier_id, product_id)
    REFERENCES public.supplier_inventory_batches (id, supplier_id, product_id) ON DELETE RESTRICT,
  CONSTRAINT purchase_order_items_quantity_positive CHECK (quantity > 0),
  CONSTRAINT purchase_order_items_received_range CHECK (received_quantity >= 0 AND received_quantity <= quantity),
  CONSTRAINT purchase_order_items_price_nonnegative CHECK (unit_price >= 0),
  CONSTRAINT purchase_order_items_total_matches CHECK (line_total = quantity * unit_price),
  CONSTRAINT purchase_order_items_order_batch_unique UNIQUE (purchase_order_id, supplier_inventory_id),
  CONSTRAINT purchase_order_items_reference_unique UNIQUE (id, organization_id, supplier_id, product_id)
);

CREATE INDEX IF NOT EXISTS purchase_order_items_order_idx
  ON public.purchase_order_items (purchase_order_id);
CREATE INDEX IF NOT EXISTS purchase_order_items_product_idx
  ON public.purchase_order_items (product_id);

CREATE TABLE IF NOT EXISTS public.inventory_batches (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES public.organizations (id) ON DELETE RESTRICT,
  product_id uuid NOT NULL REFERENCES public.products (id) ON DELETE RESTRICT,
  supplier_id uuid NOT NULL REFERENCES public.organizations (id) ON DELETE RESTRICT,
  purchase_order_item_id uuid NOT NULL UNIQUE,
  batch_number text,
  expiration_date date,
  quantity_on_hand integer NOT NULL DEFAULT 0,
  unit_cost numeric(12, 2) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT inventory_batches_source_item_fk
    FOREIGN KEY (purchase_order_item_id, organization_id, supplier_id, product_id)
    REFERENCES public.purchase_order_items (id, organization_id, supplier_id, product_id) ON DELETE RESTRICT,
  CONSTRAINT inventory_batches_quantity_nonnegative CHECK (quantity_on_hand >= 0),
  CONSTRAINT inventory_batches_cost_nonnegative CHECK (unit_cost >= 0)
);

CREATE INDEX IF NOT EXISTS inventory_batches_org_product_idx
  ON public.inventory_batches (organization_id, product_id, expiration_date);

CREATE TABLE IF NOT EXISTS public.inventory_movements (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES public.organizations (id) ON DELETE RESTRICT,
  product_id uuid NOT NULL REFERENCES public.products (id) ON DELETE RESTRICT,
  inventory_batch_id uuid NOT NULL REFERENCES public.inventory_batches (id) ON DELETE RESTRICT,
  purchase_order_item_id uuid NOT NULL REFERENCES public.purchase_order_items (id) ON DELETE RESTRICT,
  movement_type text NOT NULL,
  quantity_delta integer NOT NULL,
  unit_cost numeric(12, 2) NOT NULL,
  actor_user_id uuid NOT NULL REFERENCES auth.users (id),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT inventory_movements_type_valid CHECK (movement_type IN ('receipt', 'return', 'adjustment')),
  CONSTRAINT inventory_movements_nonzero CHECK (quantity_delta <> 0),
  CONSTRAINT inventory_movements_cost_nonnegative CHECK (unit_cost >= 0)
);

CREATE INDEX IF NOT EXISTS inventory_movements_org_product_recent_idx
  ON public.inventory_movements (organization_id, product_id, created_at DESC);
CREATE INDEX IF NOT EXISTS inventory_movements_order_item_idx
  ON public.inventory_movements (purchase_order_item_id, created_at);

DROP TRIGGER IF EXISTS products_set_updated_at ON public.products;
CREATE TRIGGER products_set_updated_at BEFORE UPDATE ON public.products
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
DROP TRIGGER IF EXISTS supplier_products_set_updated_at ON public.supplier_products;
CREATE TRIGGER supplier_products_set_updated_at BEFORE UPDATE ON public.supplier_products
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
DROP TRIGGER IF EXISTS supplier_inventory_batches_set_updated_at ON public.supplier_inventory_batches;
CREATE TRIGGER supplier_inventory_batches_set_updated_at BEFORE UPDATE ON public.supplier_inventory_batches
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
DROP TRIGGER IF EXISTS purchase_orders_set_updated_at ON public.purchase_orders;
CREATE TRIGGER purchase_orders_set_updated_at BEFORE UPDATE ON public.purchase_orders
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
DROP TRIGGER IF EXISTS inventory_batches_set_updated_at ON public.inventory_batches;
CREATE TRIGGER inventory_batches_set_updated_at BEFORE UPDATE ON public.inventory_batches
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

CREATE OR REPLACE FUNCTION app.is_org_type(p_org uuid, p_type public.organization_type)
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, app
AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.organizations o
    WHERE o.id = p_org AND o.type = p_type AND o.status = 'active' AND o.deleted_at IS NULL
  );
$$;

CREATE OR REPLACE FUNCTION app.can_read_supplier_inventory(p_supplier uuid)
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, app
AS $$
  SELECT app.is_org_member(p_supplier)
    OR (
      app.is_org_type(app.current_org_id(), 'pharmacy'::public.organization_type)
      AND app.is_org_member(app.current_org_id())
    );
$$;

DROP POLICY IF EXISTS organizations_select ON public.organizations;
CREATE POLICY organizations_select ON public.organizations FOR SELECT
  USING (
    deleted_at IS NULL
    AND (
      app.is_org_member(id)
      OR (
        type = 'supplier'::public.organization_type
        AND app.is_org_type(app.current_org_id(), 'pharmacy'::public.organization_type)
        AND app.is_org_member(app.current_org_id())
      )
    )
  );

REVOKE ALL ON FUNCTION app.is_org_type(uuid, public.organization_type) FROM PUBLIC;
REVOKE ALL ON FUNCTION app.can_read_supplier_inventory(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.is_org_type(uuid, public.organization_type) TO pharma_api, authenticated;
GRANT EXECUTE ON FUNCTION app.can_read_supplier_inventory(uuid) TO pharma_api, authenticated;

ALTER TABLE public.products ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.products FORCE ROW LEVEL SECURITY;
ALTER TABLE public.supplier_products ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.supplier_products FORCE ROW LEVEL SECURITY;
ALTER TABLE public.supplier_inventory_batches ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.supplier_inventory_batches FORCE ROW LEVEL SECURITY;
ALTER TABLE public.purchase_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.purchase_orders FORCE ROW LEVEL SECURITY;
ALTER TABLE public.purchase_order_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.purchase_order_items FORCE ROW LEVEL SECURITY;
ALTER TABLE public.inventory_batches ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.inventory_batches FORCE ROW LEVEL SECURITY;
ALTER TABLE public.inventory_movements ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.inventory_movements FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS products_select_member ON public.products;
CREATE POLICY products_select_member ON public.products FOR SELECT
  USING (active AND app.is_org_member(app.current_org_id()));

DROP POLICY IF EXISTS supplier_products_select_scoped ON public.supplier_products;
CREATE POLICY supplier_products_select_scoped ON public.supplier_products FOR SELECT
  USING (
    (supplier_id = app.current_org_id() AND app.is_org_member(supplier_id))
    OR (
      active
      AND app.is_org_type(app.current_org_id(), 'pharmacy'::public.organization_type)
      AND app.is_org_member(app.current_org_id())
      AND EXISTS (
        SELECT 1
        FROM public.supplier_inventory_batches sib
        WHERE sib.supplier_product_id = supplier_products.id
          AND sib.supplier_id = supplier_products.supplier_id
          AND sib.status = 'available'
          AND sib.deleted_at IS NULL
          AND sib.available_quantity > sib.reserved_quantity
          AND (sib.expiration_date IS NULL OR sib.expiration_date > CURRENT_DATE)
      )
    )
  );
DROP POLICY IF EXISTS supplier_products_insert_owner ON public.supplier_products;
CREATE POLICY supplier_products_insert_owner ON public.supplier_products FOR INSERT
  WITH CHECK (
    supplier_id = app.current_org_id()
    AND app.has_org_role(supplier_id, 'supplier_admin'::public.organization_role, 'supplier_staff'::public.organization_role)
  );
DROP POLICY IF EXISTS supplier_products_update_owner ON public.supplier_products;
CREATE POLICY supplier_products_update_owner ON public.supplier_products FOR UPDATE
  USING (
    supplier_id = app.current_org_id()
    AND app.has_org_role(supplier_id, 'supplier_admin'::public.organization_role, 'supplier_staff'::public.organization_role)
  )
  WITH CHECK (
    supplier_id = app.current_org_id()
    AND app.has_org_role(supplier_id, 'supplier_admin'::public.organization_role, 'supplier_staff'::public.organization_role)
  );
DROP POLICY IF EXISTS supplier_products_delete_owner ON public.supplier_products;
CREATE POLICY supplier_products_delete_owner ON public.supplier_products FOR DELETE
  USING (
    supplier_id = app.current_org_id()
    AND app.has_org_role(supplier_id, 'supplier_admin'::public.organization_role, 'supplier_staff'::public.organization_role)
  );

DROP POLICY IF EXISTS supplier_inventory_select_scoped ON public.supplier_inventory_batches;
CREATE POLICY supplier_inventory_select_scoped ON public.supplier_inventory_batches FOR SELECT
  USING (
    app.can_read_supplier_inventory(supplier_id)
    AND (
      supplier_id = app.current_org_id()
      OR (
        status = 'available'
        AND deleted_at IS NULL
        AND available_quantity > reserved_quantity
        AND (expiration_date IS NULL OR expiration_date > CURRENT_DATE)
      )
      OR EXISTS (
        SELECT 1
        FROM public.purchase_order_items poi
        JOIN public.purchase_orders po ON po.id = poi.purchase_order_id
        WHERE poi.supplier_inventory_id = supplier_inventory_batches.id
          AND (po.organization_id = app.current_org_id() OR po.supplier_id = app.current_org_id())
      )
    )
  );
DROP POLICY IF EXISTS supplier_inventory_insert_owner ON public.supplier_inventory_batches;
CREATE POLICY supplier_inventory_insert_owner ON public.supplier_inventory_batches FOR INSERT
  WITH CHECK (
    supplier_id = app.current_org_id()
    AND app.has_org_role(supplier_id, 'supplier_admin'::public.organization_role, 'supplier_staff'::public.organization_role)
  );
DROP POLICY IF EXISTS supplier_inventory_update_owner ON public.supplier_inventory_batches;
CREATE POLICY supplier_inventory_update_owner ON public.supplier_inventory_batches FOR UPDATE
  USING (
    supplier_id = app.current_org_id()
    AND app.has_org_role(supplier_id, 'supplier_admin'::public.organization_role, 'supplier_staff'::public.organization_role)
  )
  WITH CHECK (
    supplier_id = app.current_org_id()
    AND app.has_org_role(supplier_id, 'supplier_admin'::public.organization_role, 'supplier_staff'::public.organization_role)
  );
DROP POLICY IF EXISTS supplier_inventory_delete_owner ON public.supplier_inventory_batches;
CREATE POLICY supplier_inventory_delete_owner ON public.supplier_inventory_batches FOR DELETE
  USING (
    supplier_id = app.current_org_id()
    AND app.has_org_role(supplier_id, 'supplier_admin'::public.organization_role, 'supplier_staff'::public.organization_role)
  );

DROP POLICY IF EXISTS purchase_orders_select_party ON public.purchase_orders;
CREATE POLICY purchase_orders_select_party ON public.purchase_orders FOR SELECT
  USING (
    (organization_id = app.current_org_id() AND app.is_org_member(organization_id))
    OR (supplier_id = app.current_org_id() AND app.is_org_member(supplier_id))
  );
DROP POLICY IF EXISTS purchase_orders_insert_buyer ON public.purchase_orders;
CREATE POLICY purchase_orders_insert_buyer ON public.purchase_orders FOR INSERT
  WITH CHECK (
    organization_id = app.current_org_id()
    AND created_by = app.current_user_id()
    AND app.has_org_role(organization_id, 'pharmacy_admin'::public.organization_role, 'pharmacy_staff'::public.organization_role)
  );
DROP POLICY IF EXISTS purchase_orders_update_party ON public.purchase_orders;
CREATE POLICY purchase_orders_update_party ON public.purchase_orders FOR UPDATE
  USING (
    (organization_id = app.current_org_id() AND app.is_org_member(organization_id))
    OR (supplier_id = app.current_org_id() AND app.is_org_member(supplier_id))
  )
  WITH CHECK (
    (organization_id = app.current_org_id() AND app.is_org_member(organization_id))
    OR (supplier_id = app.current_org_id() AND app.is_org_member(supplier_id))
  );

DROP POLICY IF EXISTS purchase_order_items_select_party ON public.purchase_order_items;
CREATE POLICY purchase_order_items_select_party ON public.purchase_order_items FOR SELECT
  USING (
    (organization_id = app.current_org_id() AND app.is_org_member(organization_id))
    OR (supplier_id = app.current_org_id() AND app.is_org_member(supplier_id))
  );
DROP POLICY IF EXISTS purchase_order_items_insert_buyer ON public.purchase_order_items;
CREATE POLICY purchase_order_items_insert_buyer ON public.purchase_order_items FOR INSERT
  WITH CHECK (
    organization_id = app.current_org_id()
    AND app.has_org_role(organization_id, 'pharmacy_admin'::public.organization_role, 'pharmacy_staff'::public.organization_role)
  );
DROP POLICY IF EXISTS purchase_order_items_update_party ON public.purchase_order_items;
CREATE POLICY purchase_order_items_update_party ON public.purchase_order_items FOR UPDATE
  USING (
    (organization_id = app.current_org_id() AND app.is_org_member(organization_id))
    OR (supplier_id = app.current_org_id() AND app.is_org_member(supplier_id))
  )
  WITH CHECK (
    (organization_id = app.current_org_id() AND app.is_org_member(organization_id))
    OR (supplier_id = app.current_org_id() AND app.is_org_member(supplier_id))
  );

DROP POLICY IF EXISTS inventory_batches_select_org ON public.inventory_batches;
CREATE POLICY inventory_batches_select_org ON public.inventory_batches FOR SELECT
  USING (organization_id = app.current_org_id() AND app.is_org_member(organization_id));
DROP POLICY IF EXISTS inventory_batches_insert_org ON public.inventory_batches;
CREATE POLICY inventory_batches_insert_org ON public.inventory_batches FOR INSERT
  WITH CHECK (
    organization_id = app.current_org_id()
    AND app.has_org_role(organization_id, 'pharmacy_admin'::public.organization_role, 'pharmacy_staff'::public.organization_role)
  );
DROP POLICY IF EXISTS inventory_batches_update_org ON public.inventory_batches;
CREATE POLICY inventory_batches_update_org ON public.inventory_batches FOR UPDATE
  USING (
    organization_id = app.current_org_id()
    AND app.has_org_role(organization_id, 'pharmacy_admin'::public.organization_role, 'pharmacy_staff'::public.organization_role)
  )
  WITH CHECK (
    organization_id = app.current_org_id()
    AND app.has_org_role(organization_id, 'pharmacy_admin'::public.organization_role, 'pharmacy_staff'::public.organization_role)
  );

DROP POLICY IF EXISTS inventory_movements_select_org ON public.inventory_movements;
CREATE POLICY inventory_movements_select_org ON public.inventory_movements FOR SELECT
  USING (organization_id = app.current_org_id() AND app.is_org_member(organization_id));
DROP POLICY IF EXISTS inventory_movements_insert_org ON public.inventory_movements;
CREATE POLICY inventory_movements_insert_org ON public.inventory_movements FOR INSERT
  WITH CHECK (
    organization_id = app.current_org_id()
    AND actor_user_id = app.current_user_id()
    AND app.has_org_role(organization_id, 'pharmacy_admin'::public.organization_role, 'pharmacy_staff'::public.organization_role)
  );

GRANT SELECT ON public.products TO pharma_api;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.supplier_products, public.supplier_inventory_batches TO pharma_api;
GRANT SELECT, INSERT, UPDATE ON public.purchase_orders, public.purchase_order_items TO pharma_api;
GRANT SELECT, INSERT, UPDATE ON public.inventory_batches TO pharma_api;
GRANT SELECT, INSERT ON public.inventory_movements TO pharma_api;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO pharma_api;

REVOKE UPDATE, DELETE ON public.inventory_movements FROM pharma_api;
