"""Store the member's email (from the verified JWT) for the member admin UI.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-25

Emails are copied from the JWT `email` claim when a user creates an
organization or accepts an invitation; clients never supply them. They are
visible only to fellow active members (existing members_select policy).
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

UPGRADE = r"""
ALTER TABLE public.organization_members ADD COLUMN email text
  CHECK (email IS NULL OR (email = lower(email) AND length(email) <= 320));

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

CREATE OR REPLACE FUNCTION app_private.accept_invitation(p_token text) RETURNS uuid
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
  IF NOT FOUND
     OR v_inv.accepted_at IS NOT NULL
     OR v_inv.revoked_at IS NOT NULL
     OR v_inv.expires_at <= now()
     OR v_inv.email <> v_email THEN
    RAISE EXCEPTION 'invitation not found' USING ERRCODE = 'P0002';
  END IF;

  INSERT INTO public.organization_members
      (organization_id, user_id, role, status, invited_by, email)
    VALUES (v_inv.organization_id, v_uid, v_inv.role, 'active', v_inv.invited_by, v_email)
  ON CONFLICT (organization_id, user_id) DO UPDATE
    SET role = EXCLUDED.role, status = 'active', revoked_at = NULL,
        invited_by = EXCLUDED.invited_by, email = EXCLUDED.email
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

REVOKE ALL ON FUNCTION app_private.create_organization(text, text),
  app_private.accept_invitation(text) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION app_private.create_organization(text, text),
  app_private.accept_invitation(text) TO authenticated;
"""

DOWNGRADE = r"""
ALTER TABLE public.organization_members DROP COLUMN IF EXISTS email;
"""


def upgrade() -> None:
    op.get_bind().connection.driver_connection.execute(UPGRADE)


def _without_email(sql: str) -> str:
    """The function bodies above, minus the email column (pre-0005 behaviour)."""
    body = sql[sql.index("CREATE OR REPLACE FUNCTION app_private.create_organization") :]
    for old, new in [
        (
            "(organization_id, user_id, role, status, email)",
            "(organization_id, user_id, role, status)",
        ),
        ("'owner', 'active', app_private.current_user_email())", "'owner', 'active')"),
        (
            "(organization_id, user_id, role, status, invited_by, email)",
            "(organization_id, user_id, role, status, invited_by)",
        ),
        ("'active', v_inv.invited_by, v_email)", "'active', v_inv.invited_by)"),
        (
            "invited_by = EXCLUDED.invited_by, email = EXCLUDED.email",
            "invited_by = EXCLUDED.invited_by",
        ),
    ]:
        if old not in body:
            raise RuntimeError(f"0005 downgrade: expected text not found: {old}")
        body = body.replace(old, new)
    return body


def downgrade() -> None:
    raw = op.get_bind().connection.driver_connection
    raw.execute(_without_email(UPGRADE))
    raw.execute(DOWNGRADE)
