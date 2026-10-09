-- PharmaIntelligence Phase 1: identity, tenancy, RBAC helpers, audit, RLS.
-- Apply in the Supabase SQL editor or via the CLI.
-- organization_id is the tenant. There is no separate tenant_id.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE SCHEMA IF NOT EXISTS app;

GRANT USAGE ON SCHEMA app TO anon, authenticated, service_role;

-- ---------------------------------------------------------------------------
-- Enums
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'organization_type') THEN
    CREATE TYPE public.organization_type AS ENUM ('pharmacy', 'supplier', 'platform');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'organization_status') THEN
    CREATE TYPE public.organization_status AS ENUM ('active', 'suspended');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'membership_status') THEN
    CREATE TYPE public.membership_status AS ENUM ('active', 'disabled');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'organization_role') THEN
    CREATE TYPE public.organization_role AS ENUM (
      'platform_admin',
      'pharmacy_admin',
      'pharmacy_staff',
      'supplier_admin',
      'supplier_staff'
    );
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'account_kind') THEN
    CREATE TYPE public.account_kind AS ENUM ('customer', 'staff');
  END IF;
END $$;

-- ---------------------------------------------------------------------------
-- Session helpers (FastAPI sets GUCs; PostgREST uses auth.uid())
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION app.current_user_id()
RETURNS uuid
LANGUAGE sql
STABLE
AS $$
  SELECT COALESCE(
    NULLIF(current_setting('app.user_id', true), '')::uuid,
    auth.uid()
  );
$$;

CREATE OR REPLACE FUNCTION app.current_org_id()
RETURNS uuid
LANGUAGE sql
STABLE
AS $$
  SELECT NULLIF(current_setting('app.organization_id', true), '')::uuid;
$$;

CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

-- ---------------------------------------------------------------------------
-- Tables
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.profiles (
  user_id uuid PRIMARY KEY REFERENCES auth.users (id) ON DELETE CASCADE,
  full_name text NOT NULL DEFAULT '',
  phone text,
  account_kind public.account_kind NOT NULL DEFAULT 'customer',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz
);

CREATE TABLE IF NOT EXISTS public.organizations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  slug text NOT NULL,
  type public.organization_type NOT NULL,
  status public.organization_status NOT NULL DEFAULT 'active',
  created_by uuid REFERENCES auth.users (id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT organizations_name_not_blank CHECK (char_length(btrim(name)) > 0),
  CONSTRAINT organizations_slug_format CHECK (slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$')
);

CREATE UNIQUE INDEX IF NOT EXISTS organizations_slug_live_idx
  ON public.organizations (slug)
  WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS public.organization_members (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES public.organizations (id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
  role public.organization_role NOT NULL,
  status public.membership_status NOT NULL DEFAULT 'active',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT organization_members_unique_live UNIQUE (organization_id, user_id)
);

CREATE INDEX IF NOT EXISTS organization_members_user_idx
  ON public.organization_members (user_id)
  WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS organization_members_org_idx
  ON public.organization_members (organization_id)
  WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS public.organization_invites (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES public.organizations (id) ON DELETE CASCADE,
  code_hash text NOT NULL,
  role public.organization_role NOT NULL,
  expires_at timestamptz NOT NULL,
  created_by uuid NOT NULL REFERENCES auth.users (id),
  accepted_by uuid REFERENCES auth.users (id),
  accepted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  revoked_at timestamptz,
  CONSTRAINT organization_invites_code_hash_unique UNIQUE (code_hash)
);

CREATE INDEX IF NOT EXISTS organization_invites_org_idx
  ON public.organization_invites (organization_id);

CREATE TABLE IF NOT EXISTS public.audit_logs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid REFERENCES public.organizations (id),
  actor_user_id uuid REFERENCES auth.users (id),
  action text NOT NULL,
  resource_type text NOT NULL,
  resource_id text,
  result text NOT NULL DEFAULT 'success',
  request_id text,
  ip inet,
  user_agent text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT audit_logs_action_not_blank CHECK (char_length(btrim(action)) > 0)
);

CREATE INDEX IF NOT EXISTS audit_logs_org_created_idx
  ON public.audit_logs (organization_id, created_at DESC);

CREATE INDEX IF NOT EXISTS audit_logs_actor_created_idx
  ON public.audit_logs (actor_user_id, created_at DESC);

DROP TRIGGER IF EXISTS profiles_set_updated_at ON public.profiles;
CREATE TRIGGER profiles_set_updated_at
  BEFORE UPDATE ON public.profiles
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS organizations_set_updated_at ON public.organizations;
CREATE TRIGGER organizations_set_updated_at
  BEFORE UPDATE ON public.organizations
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS organization_members_set_updated_at ON public.organization_members;
CREATE TRIGGER organization_members_set_updated_at
  BEFORE UPDATE ON public.organization_members
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- ---------------------------------------------------------------------------
-- Auth → profile
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  kind public.account_kind;
BEGIN
  kind := COALESCE(NULLIF(NEW.raw_user_meta_data->>'account_kind', '')::public.account_kind, 'customer');
  INSERT INTO public.profiles (user_id, full_name, account_kind)
  VALUES (
    NEW.id,
    COALESCE(NEW.raw_user_meta_data->>'full_name', ''),
    kind
  )
  ON CONFLICT (user_id) DO NOTHING;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- ---------------------------------------------------------------------------
-- SECURITY DEFINER membership checks (avoid RLS recursion)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION app.is_org_member(p_org uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM public.organization_members m
    JOIN public.organizations o ON o.id = m.organization_id
    WHERE m.organization_id = p_org
      AND m.user_id = app.current_user_id()
      AND m.status = 'active'
      AND m.deleted_at IS NULL
      AND o.deleted_at IS NULL
      AND o.status = 'active'
  );
$$;

CREATE OR REPLACE FUNCTION app.has_org_role(p_org uuid, VARIADIC p_roles public.organization_role[])
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM public.organization_members m
    JOIN public.organizations o ON o.id = m.organization_id
    WHERE m.organization_id = p_org
      AND m.user_id = app.current_user_id()
      AND m.role = ANY (p_roles)
      AND m.status = 'active'
      AND m.deleted_at IS NULL
      AND o.deleted_at IS NULL
  );
$$;

CREATE OR REPLACE FUNCTION app.accept_organization_invite(p_code_hash text)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  invite_row public.organization_invites%ROWTYPE;
  uid uuid := app.current_user_id();
BEGIN
  IF uid IS NULL THEN
    RAISE EXCEPTION 'not authenticated';
  END IF;

  SELECT * INTO invite_row
  FROM public.organization_invites
  WHERE code_hash = p_code_hash
  FOR UPDATE;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'invite not found';
  END IF;
  IF invite_row.revoked_at IS NOT NULL THEN
    RAISE EXCEPTION 'invite revoked';
  END IF;
  IF invite_row.accepted_at IS NOT NULL THEN
    RAISE EXCEPTION 'invite already used';
  END IF;
  IF invite_row.expires_at < now() THEN
    RAISE EXCEPTION 'invite expired';
  END IF;

  INSERT INTO public.organization_members (organization_id, user_id, role, status)
  VALUES (invite_row.organization_id, uid, invite_row.role, 'active')
  ON CONFLICT (organization_id, user_id) DO UPDATE
    SET role = EXCLUDED.role,
        status = 'active',
        deleted_at = NULL,
        updated_at = now();

  UPDATE public.organization_invites
  SET accepted_by = uid, accepted_at = now()
  WHERE id = invite_row.id;

  RETURN invite_row.organization_id;
END;
$$;

REVOKE ALL ON FUNCTION app.is_org_member(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION app.has_org_role(uuid, public.organization_role[]) FROM PUBLIC;
REVOKE ALL ON FUNCTION app.accept_organization_invite(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.is_org_member(uuid) TO authenticated, service_role, anon;
GRANT EXECUTE ON FUNCTION app.has_org_role(uuid, public.organization_role[]) TO authenticated, service_role, anon;
GRANT EXECUTE ON FUNCTION app.accept_organization_invite(text) TO authenticated, service_role;

-- ---------------------------------------------------------------------------
-- Grants
-- ---------------------------------------------------------------------------
REVOKE ALL ON TABLE public.profiles FROM PUBLIC, anon;
REVOKE ALL ON TABLE public.organizations FROM PUBLIC, anon;
REVOKE ALL ON TABLE public.organization_members FROM PUBLIC, anon;
REVOKE ALL ON TABLE public.organization_invites FROM PUBLIC, anon;
REVOKE ALL ON TABLE public.audit_logs FROM PUBLIC, anon;

GRANT SELECT, INSERT, UPDATE ON TABLE public.profiles TO authenticated;
GRANT SELECT, INSERT, UPDATE ON TABLE public.organizations TO authenticated;
GRANT SELECT, INSERT, UPDATE ON TABLE public.organization_members TO authenticated;
GRANT SELECT, INSERT, UPDATE ON TABLE public.organization_invites TO authenticated;
GRANT SELECT, INSERT ON TABLE public.audit_logs TO authenticated;

GRANT ALL ON TABLE public.profiles TO service_role;
GRANT ALL ON TABLE public.organizations TO service_role;
GRANT ALL ON TABLE public.organization_members TO service_role;
GRANT ALL ON TABLE public.organization_invites TO service_role;
GRANT ALL ON TABLE public.audit_logs TO service_role;

-- Optional non-superuser for FastAPI. Superuser connections bypass RLS.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pharma_api') THEN
    CREATE ROLE pharma_api NOINHERIT NOBYPASSRLS;
  END IF;
END $$;

GRANT USAGE ON SCHEMA public, app TO pharma_api;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO pharma_api;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO pharma_api;
GRANT EXECUTE ON FUNCTION app.current_user_id() TO pharma_api;
GRANT EXECUTE ON FUNCTION app.current_org_id() TO pharma_api;
GRANT EXECUTE ON FUNCTION app.is_org_member(uuid) TO pharma_api;
GRANT EXECUTE ON FUNCTION app.has_org_role(uuid, public.organization_role[]) TO pharma_api;
GRANT EXECUTE ON FUNCTION app.accept_organization_invite(text) TO pharma_api;

-- ---------------------------------------------------------------------------
-- RLS  (FORCE so table owners are included; superusers still bypass)
-- ---------------------------------------------------------------------------
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.profiles FORCE ROW LEVEL SECURITY;
ALTER TABLE public.organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.organizations FORCE ROW LEVEL SECURITY;
ALTER TABLE public.organization_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.organization_members FORCE ROW LEVEL SECURITY;
ALTER TABLE public.organization_invites ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.organization_invites FORCE ROW LEVEL SECURITY;
ALTER TABLE public.audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.audit_logs FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS profiles_select ON public.profiles;
CREATE POLICY profiles_select ON public.profiles
  FOR SELECT
  USING (
    user_id = app.current_user_id()
    OR EXISTS (
      SELECT 1
      FROM public.organization_members mine
      JOIN public.organization_members theirs
        ON theirs.organization_id = mine.organization_id
      WHERE mine.user_id = app.current_user_id()
        AND mine.status = 'active'
        AND mine.deleted_at IS NULL
        AND theirs.user_id = profiles.user_id
        AND theirs.status = 'active'
        AND theirs.deleted_at IS NULL
    )
  );

DROP POLICY IF EXISTS profiles_insert ON public.profiles;
CREATE POLICY profiles_insert ON public.profiles
  FOR INSERT
  WITH CHECK (user_id = app.current_user_id());

DROP POLICY IF EXISTS profiles_update ON public.profiles;
CREATE POLICY profiles_update ON public.profiles
  FOR UPDATE
  USING (user_id = app.current_user_id())
  WITH CHECK (user_id = app.current_user_id());

DROP POLICY IF EXISTS organizations_select ON public.organizations;
CREATE POLICY organizations_select ON public.organizations
  FOR SELECT
  USING (deleted_at IS NULL AND app.is_org_member(id));

DROP POLICY IF EXISTS organizations_insert ON public.organizations;
CREATE POLICY organizations_insert ON public.organizations
  FOR INSERT
  WITH CHECK (app.current_user_id() IS NOT NULL AND created_by = app.current_user_id());

DROP POLICY IF EXISTS organizations_update ON public.organizations;
CREATE POLICY organizations_update ON public.organizations
  FOR UPDATE
  USING (
    app.has_org_role(
      id,
      'platform_admin'::public.organization_role,
      'pharmacy_admin'::public.organization_role,
      'supplier_admin'::public.organization_role
    )
  )
  WITH CHECK (
    app.has_org_role(
      id,
      'platform_admin'::public.organization_role,
      'pharmacy_admin'::public.organization_role,
      'supplier_admin'::public.organization_role
    )
  );

DROP POLICY IF EXISTS members_select ON public.organization_members;
CREATE POLICY members_select ON public.organization_members
  FOR SELECT
  USING (deleted_at IS NULL AND app.is_org_member(organization_id));

DROP POLICY IF EXISTS members_insert ON public.organization_members;
CREATE POLICY members_insert ON public.organization_members
  FOR INSERT
  WITH CHECK (
    user_id = app.current_user_id()
    OR app.has_org_role(
      organization_id,
      'platform_admin'::public.organization_role,
      'pharmacy_admin'::public.organization_role,
      'supplier_admin'::public.organization_role
    )
  );

DROP POLICY IF EXISTS members_update ON public.organization_members;
CREATE POLICY members_update ON public.organization_members
  FOR UPDATE
  USING (
    app.has_org_role(
      organization_id,
      'platform_admin'::public.organization_role,
      'pharmacy_admin'::public.organization_role,
      'supplier_admin'::public.organization_role
    )
  )
  WITH CHECK (
    app.has_org_role(
      organization_id,
      'platform_admin'::public.organization_role,
      'pharmacy_admin'::public.organization_role,
      'supplier_admin'::public.organization_role
    )
  );

DROP POLICY IF EXISTS invites_select ON public.organization_invites;
CREATE POLICY invites_select ON public.organization_invites
  FOR SELECT
  USING (
    app.has_org_role(
      organization_id,
      'platform_admin'::public.organization_role,
      'pharmacy_admin'::public.organization_role,
      'supplier_admin'::public.organization_role
    )
  );

DROP POLICY IF EXISTS invites_insert ON public.organization_invites;
CREATE POLICY invites_insert ON public.organization_invites
  FOR INSERT
  WITH CHECK (
    created_by = app.current_user_id()
    AND app.has_org_role(
      organization_id,
      'platform_admin'::public.organization_role,
      'pharmacy_admin'::public.organization_role,
      'supplier_admin'::public.organization_role
    )
  );

DROP POLICY IF EXISTS invites_update ON public.organization_invites;
CREATE POLICY invites_update ON public.organization_invites
  FOR UPDATE
  USING (
    app.has_org_role(
      organization_id,
      'platform_admin'::public.organization_role,
      'pharmacy_admin'::public.organization_role,
      'supplier_admin'::public.organization_role
    )
  )
  WITH CHECK (
    app.has_org_role(
      organization_id,
      'platform_admin'::public.organization_role,
      'pharmacy_admin'::public.organization_role,
      'supplier_admin'::public.organization_role
    )
  );

DROP POLICY IF EXISTS audit_select ON public.audit_logs;
CREATE POLICY audit_select ON public.audit_logs
  FOR SELECT
  USING (
    actor_user_id = app.current_user_id()
    OR (
      organization_id IS NOT NULL
      AND app.has_org_role(
        organization_id,
        'platform_admin'::public.organization_role,
        'pharmacy_admin'::public.organization_role,
        'supplier_admin'::public.organization_role
      )
    )
  );

DROP POLICY IF EXISTS audit_insert ON public.audit_logs;
CREATE POLICY audit_insert ON public.audit_logs
  FOR INSERT
  WITH CHECK (
    actor_user_id = app.current_user_id()
    OR app.current_user_id() IS NULL
  );
