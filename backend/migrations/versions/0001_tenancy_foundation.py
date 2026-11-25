"""Tenancy foundation: organizations, members, invitations, roles and RLS.

Revision ID: 0001
Revises:
Create Date: 2026-11-25

Security model (see docs/decisions/0004-tenant-isolation-model.md):
- The API logs in as `atlas_api` (LOGIN NOINHERIT, no table privileges) and
  runs every request as `SET LOCAL ROLE authenticated` with the verified JWT
  claims in `request.jwt.claims`. RLS policies read the user from there.
- Each tenant table has RLS and separate SELECT/INSERT/UPDATE/DELETE policies.
- Supabase's default privileges grant anon/authenticated ALL on new tables and
  EXECUTE on new functions; we revoke those and grant the minimum explicitly.
- Only two SECURITY DEFINER entry points bypass RLS: create_organization and
  accept_invitation. Both derive identity from the JWT claims, never arguments.
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

UPGRADE = r"""
-- ---------------------------------------------------------------- roles
-- Roles are cluster-wide. `authenticated`/`anon` already exist on Supabase;
-- create them on plain Postgres so migrations are portable.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
    CREATE ROLE anon NOLOGIN NOINHERIT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
    CREATE ROLE authenticated NOLOGIN NOINHERIT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'atlas_api') THEN
    -- LOGIN is enabled and the password set by `python -m app.db.manage migrate`.
    CREATE ROLE atlas_api NOLOGIN NOINHERIT NOCREATEDB NOCREATEROLE NOBYPASSRLS;
  END IF;
END $$;
GRANT authenticated TO atlas_api;
GRANT CONNECT ON DATABASE current_database_placeholder TO atlas_api;

-- ---------------------------------------------------------------- helpers
CREATE SCHEMA app_private;
REVOKE ALL ON SCHEMA app_private FROM PUBLIC;
GRANT USAGE ON SCHEMA app_private TO authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA app_private REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

-- Identity comes only from claims the API sets after verifying the JWT.
CREATE FUNCTION app_private.current_user_id() RETURNS uuid
LANGUAGE sql STABLE SET search_path = '' AS $$
  SELECT nullif(nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub', '')::uuid
$$;

CREATE FUNCTION app_private.current_user_email() RETURNS text
LANGUAGE sql STABLE SET search_path = '' AS $$
  SELECT lower(nullif(
    nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'email', ''
  ))
$$;

CREATE FUNCTION app_private.set_updated_at() RETURNS trigger
LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END $$;

-- ---------------------------------------------------------------- tables
CREATE TABLE public.organizations (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name        text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 200),
  slug        text NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$'),
  plan        text NOT NULL DEFAULT 'free' CHECK (plan IN ('free', 'pro', 'enterprise')),
  created_by  uuid NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.organization_members (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id  uuid NOT NULL REFERENCES public.organizations (id) ON DELETE CASCADE,
  user_id          uuid NOT NULL,
  role             text NOT NULL CHECK (role IN ('owner', 'admin', 'member', 'viewer')),
  status           text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked')),
  invited_by       uuid,
  revoked_at       timestamptz,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (organization_id, user_id),
  -- Target for tenant-scoped composite foreign keys from other tables.
  UNIQUE (organization_id, id),
  -- The inviter must be a member of the same organization.
  FOREIGN KEY (organization_id, invited_by)
    REFERENCES public.organization_members (organization_id, user_id),
  CHECK ((status = 'revoked') = (revoked_at IS NOT NULL))
);
CREATE INDEX organization_members_user_idx ON public.organization_members (user_id)
  WHERE status = 'active';
-- Exactly one owner per organization (ownership transfer is not supported yet).
CREATE UNIQUE INDEX organization_members_one_owner ON public.organization_members (organization_id)
  WHERE role = 'owner';

CREATE TABLE public.organization_invitations (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id  uuid NOT NULL REFERENCES public.organizations (id) ON DELETE CASCADE,
  email            text NOT NULL CHECK (email = lower(email) AND email LIKE '%_@_%'),
  role             text NOT NULL CHECK (role IN ('admin', 'member', 'viewer')),
  token_hash       text NOT NULL UNIQUE,
  invited_by       uuid NOT NULL,
  expires_at       timestamptz NOT NULL,
  accepted_at      timestamptz,
  accepted_by      uuid,
  revoked_at       timestamptz,
  created_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (organization_id, id),
  FOREIGN KEY (organization_id, invited_by)
    REFERENCES public.organization_members (organization_id, user_id),
  CHECK (expires_at > created_at)
);
-- One pending invitation per email per organization.
CREATE UNIQUE INDEX organization_invitations_pending_email
  ON public.organization_invitations (organization_id, email)
  WHERE accepted_at IS NULL AND revoked_at IS NULL;

CREATE TRIGGER organizations_updated_at BEFORE UPDATE ON public.organizations
  FOR EACH ROW EXECUTE FUNCTION app_private.set_updated_at();
CREATE TRIGGER organization_members_updated_at BEFORE UPDATE ON public.organization_members
  FOR EACH ROW EXECUTE FUNCTION app_private.set_updated_at();

-- ---------------------------------------------------------------- membership helpers
-- SECURITY DEFINER so policies on organization_members can consult it without
-- recursing into their own RLS. They only ever describe the *current* user.
CREATE FUNCTION app_private.member_role(p_org uuid) RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT m.role FROM public.organization_members m
  WHERE m.organization_id = p_org
    AND m.user_id = app_private.current_user_id()
    AND m.status = 'active'
$$;

CREATE FUNCTION app_private.is_member(p_org uuid) RETURNS boolean
LANGUAGE sql STABLE SET search_path = '' AS $$
  SELECT app_private.member_role(p_org) IS NOT NULL
$$;

-- ---------------------------------------------------------------- privileges
REVOKE ALL ON public.organizations, public.organization_members, public.organization_invitations
  FROM PUBLIC, anon, authenticated;
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
    EXECUTE 'REVOKE ALL ON public.organizations, public.organization_members,
             public.organization_invitations FROM service_role';
  END IF;
END $$;

GRANT SELECT ON public.organizations TO authenticated;
GRANT UPDATE (name) ON public.organizations TO authenticated;

GRANT SELECT ON public.organization_members TO authenticated;
GRANT UPDATE (role, status, revoked_at) ON public.organization_members TO authenticated;

GRANT SELECT, DELETE ON public.organization_invitations TO authenticated;
GRANT INSERT (organization_id, email, role, token_hash, invited_by, expires_at)
  ON public.organization_invitations TO authenticated;
GRANT UPDATE (revoked_at) ON public.organization_invitations TO authenticated;

-- ---------------------------------------------------------------- RLS
ALTER TABLE public.organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.organization_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.organization_invitations ENABLE ROW LEVEL SECURITY;

-- organizations
CREATE POLICY organizations_select ON public.organizations FOR SELECT TO authenticated
  USING (app_private.is_member(id));
-- Creation goes through app_private.create_organization only.
CREATE POLICY organizations_insert ON public.organizations FOR INSERT TO authenticated
  WITH CHECK (false);
CREATE POLICY organizations_update ON public.organizations FOR UPDATE TO authenticated
  USING (app_private.member_role(id) = 'owner')
  WITH CHECK (app_private.member_role(id) = 'owner');
CREATE POLICY organizations_delete ON public.organizations FOR DELETE TO authenticated
  USING (app_private.member_role(id) = 'owner');

-- organization_members
CREATE POLICY members_select ON public.organization_members FOR SELECT TO authenticated
  USING (app_private.is_member(organization_id));
-- Joining goes through create_organization / accept_invitation only.
CREATE POLICY members_insert ON public.organization_members FOR INSERT TO authenticated
  WITH CHECK (false);
-- USING sees the old row, WITH CHECK the new one. Nobody edits their own row
-- (no self-promotion); owners manage non-owners; admins manage members/viewers
-- and can only assign member/viewer. Nobody can grant owner.
CREATE POLICY members_update ON public.organization_members FOR UPDATE TO authenticated
  USING (
    user_id <> app_private.current_user_id()
    AND (
      (app_private.member_role(organization_id) = 'owner' AND role <> 'owner')
      OR (app_private.member_role(organization_id) = 'admin' AND role IN ('member', 'viewer'))
    )
  )
  WITH CHECK (
    user_id <> app_private.current_user_id()
    AND (
      (app_private.member_role(organization_id) = 'owner' AND role IN ('admin', 'member', 'viewer'))
      OR (app_private.member_role(organization_id) = 'admin' AND role IN ('member', 'viewer'))
    )
  );
-- Memberships are revoked (status = 'revoked'), never hard-deleted, to keep history.
CREATE POLICY members_delete ON public.organization_members FOR DELETE TO authenticated
  USING (false);

-- organization_invitations
CREATE POLICY invitations_select ON public.organization_invitations FOR SELECT TO authenticated
  USING (app_private.member_role(organization_id) IN ('owner', 'admin'));
CREATE POLICY invitations_insert ON public.organization_invitations FOR INSERT TO authenticated
  WITH CHECK (
    invited_by = app_private.current_user_id()
    AND (
      app_private.member_role(organization_id) = 'owner'
      OR (app_private.member_role(organization_id) = 'admin' AND role IN ('member', 'viewer'))
    )
  );
CREATE POLICY invitations_update ON public.organization_invitations FOR UPDATE TO authenticated
  USING (app_private.member_role(organization_id) IN ('owner', 'admin'))
  WITH CHECK (app_private.member_role(organization_id) IN ('owner', 'admin'));
CREATE POLICY invitations_delete ON public.organization_invitations FOR DELETE TO authenticated
  USING (app_private.member_role(organization_id) IN ('owner', 'admin'));

-- ---------------------------------------------------------------- definer entry points
CREATE FUNCTION app_private.create_organization(p_name text, p_slug text) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  v_uid uuid := app_private.current_user_id();
  v_org uuid;
BEGIN
  IF v_uid IS NULL THEN
    RAISE EXCEPTION 'not authenticated' USING ERRCODE = '28000';
  END IF;
  INSERT INTO public.organizations (name, slug, created_by)
    VALUES (p_name, p_slug, v_uid) RETURNING id INTO v_org;
  INSERT INTO public.organization_members (organization_id, user_id, role, status)
    VALUES (v_org, v_uid, 'owner', 'active');
  RETURN v_org;
END $$;

CREATE FUNCTION app_private.accept_invitation(p_token text) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  v_uid   uuid := app_private.current_user_id();
  v_email text := app_private.current_user_email();
  v_inv   public.organization_invitations;
  v_member uuid;
BEGIN
  IF v_uid IS NULL OR v_email IS NULL THEN
    RAISE EXCEPTION 'not authenticated' USING ERRCODE = '28000';
  END IF;

  SELECT * INTO v_inv FROM public.organization_invitations
    WHERE token_hash = encode(sha256(convert_to(p_token, 'UTF8')), 'hex')
    FOR UPDATE;
  -- One error for every failure so the endpoint is not an oracle.
  IF NOT FOUND
     OR v_inv.accepted_at IS NOT NULL
     OR v_inv.revoked_at IS NOT NULL
     OR v_inv.expires_at <= now()
     OR v_inv.email <> v_email THEN
    RAISE EXCEPTION 'invitation not found' USING ERRCODE = 'P0002';
  END IF;

  -- New member, or re-activate a revoked one. Active members are left alone.
  INSERT INTO public.organization_members (organization_id, user_id, role, status, invited_by)
    VALUES (v_inv.organization_id, v_uid, v_inv.role, 'active', v_inv.invited_by)
  ON CONFLICT (organization_id, user_id) DO UPDATE
    SET role = EXCLUDED.role, status = 'active', revoked_at = NULL,
        invited_by = EXCLUDED.invited_by
    WHERE public.organization_members.status = 'revoked'
  RETURNING id INTO v_member;
  IF v_member IS NULL THEN
    RAISE EXCEPTION 'already a member' USING ERRCODE = '23505';
  END IF;

  UPDATE public.organization_invitations
    SET accepted_at = now(), accepted_by = v_uid
    WHERE id = v_inv.id;
  RETURN v_member;
END $$;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA app_private FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION
  app_private.current_user_id(),
  app_private.current_user_email(),
  app_private.member_role(uuid),
  app_private.is_member(uuid),
  app_private.create_organization(text, text),
  app_private.accept_invitation(text)
TO authenticated;
"""

DOWNGRADE = r"""
DROP TABLE IF EXISTS public.organization_invitations;
DROP TABLE IF EXISTS public.organization_members;
DROP TABLE IF EXISTS public.organizations;
DROP SCHEMA IF EXISTS app_private CASCADE;
REVOKE CONNECT ON DATABASE current_database_placeholder FROM atlas_api;
-- Roles are cluster-wide and may be used by other databases; they are kept.
"""


def _run(sql: str) -> None:
    # Raw psycopg execute without parameters: multi-statement SQL and literal
    # '%' are passed through untouched, inside Alembic's transaction.
    raw = op.get_bind().connection.driver_connection
    (db,) = raw.execute("SELECT current_database()").fetchone()
    quoted = '"' + db.replace('"', '""') + '"'
    raw.execute(sql.replace("current_database_placeholder", quoted))


def upgrade() -> None:
    _run(UPGRADE)


def downgrade() -> None:
    _run(DOWNGRADE)
