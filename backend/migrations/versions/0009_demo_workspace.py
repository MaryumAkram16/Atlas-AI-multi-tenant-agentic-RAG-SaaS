"""Public demo workspace for anonymous visitors.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-26

- The operator chooses at most one demo organization (app_private.demo_config,
  set by `python -m app.db.manage demo-config`, never through the API).
- An anonymous visitor (Supabase anonymous sign-in: a real, private user whose
  JWT carries is_anonymous=true) can join only that organization, only as a
  viewer: read and chat, no uploads. Each visitor's chats stay private.
- Anonymous users cannot create organizations (and cannot accept invitations,
  which already require an email), and see only their own membership row.
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

UPGRADE = r"""
CREATE TABLE app_private.demo_config (
  singleton        boolean PRIMARY KEY DEFAULT true CHECK (singleton),
  organization_id  uuid NOT NULL REFERENCES public.organizations (id) ON DELETE CASCADE,
  updated_at       timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE app_private.demo_config ENABLE ROW LEVEL SECURITY;  -- no policies: deny all
REVOKE ALL ON app_private.demo_config FROM PUBLIC, anon, authenticated;

CREATE FUNCTION app_private.is_anonymous() RETURNS boolean
LANGUAGE sql STABLE SET search_path = '' AS $$
  SELECT coalesce(
    (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'is_anonymous')::boolean,
    false)
$$;

-- Join the configured demo organization as a viewer. Returns its id, or NULL
-- when no demo is configured. A revoked demo membership stays revoked.
CREATE FUNCTION app_private.join_demo() RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  v_uid uuid := app_private.current_user_id();
  v_org uuid;
BEGIN
  IF v_uid IS NULL THEN
    RAISE EXCEPTION 'not authenticated' USING ERRCODE = '28000';
  END IF;
  IF NOT app_private.is_anonymous() THEN
    RAISE EXCEPTION 'the demo workspace is for anonymous visitors' USING ERRCODE = '42501';
  END IF;
  SELECT organization_id INTO v_org FROM app_private.demo_config;
  IF v_org IS NULL THEN
    RETURN NULL;
  END IF;
  INSERT INTO public.organization_members (organization_id, user_id, role, status)
    VALUES (v_org, v_uid, 'viewer', 'active')
    ON CONFLICT (organization_id, user_id) DO NOTHING;
  RETURN v_org;
END $$;

CREATE OR REPLACE FUNCTION app_private.create_organization(p_name text, p_slug text) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  v_uid uuid := app_private.current_user_id();
  v_org uuid;
BEGIN
  IF v_uid IS NULL THEN
    RAISE EXCEPTION 'not authenticated' USING ERRCODE = '28000';
  END IF;
  IF app_private.is_anonymous() THEN
    RAISE EXCEPTION 'anonymous users cannot create organizations' USING ERRCODE = '42501';
  END IF;
  INSERT INTO public.organizations (name, slug, created_by)
    VALUES (p_name, p_slug, v_uid) RETURNING id INTO v_org;
  INSERT INTO public.organization_members (organization_id, user_id, role, status, email)
    VALUES (v_org, v_uid, 'owner', 'active', app_private.current_user_email());
  RETURN v_org;
END $$;

-- Anonymous visitors see only their own membership (not the member list and
-- its emails).
DROP POLICY members_select ON public.organization_members;
CREATE POLICY members_select ON public.organization_members FOR SELECT TO authenticated
  USING (
    app_private.is_member(organization_id)
    AND (NOT app_private.is_anonymous() OR user_id = app_private.current_user_id())
  );

REVOKE ALL ON FUNCTION app_private.is_anonymous(), app_private.join_demo() FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION app_private.is_anonymous(), app_private.join_demo() TO authenticated;
"""

DOWNGRADE = r"""
DROP POLICY members_select ON public.organization_members;
CREATE POLICY members_select ON public.organization_members FOR SELECT TO authenticated
  USING (app_private.is_member(organization_id));
CREATE OR REPLACE FUNCTION app_private.create_organization(p_name text, p_slug text) RETURNS uuid
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
  INSERT INTO public.organization_members (organization_id, user_id, role, status, email)
    VALUES (v_org, v_uid, 'owner', 'active', app_private.current_user_email());
  RETURN v_org;
END $$;
DROP FUNCTION IF EXISTS app_private.join_demo();
DROP FUNCTION IF EXISTS app_private.is_anonymous();
DROP TABLE IF EXISTS app_private.demo_config;
"""


def upgrade() -> None:
    op.get_bind().connection.driver_connection.execute(UPGRADE)


def downgrade() -> None:
    op.get_bind().connection.driver_connection.execute(DOWNGRADE)
