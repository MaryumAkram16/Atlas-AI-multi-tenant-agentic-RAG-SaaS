"""Hardening: trigger-written audit logs, rate limiting, quota usage, and
trace context on jobs.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-25

- audit_logs rows are written only by AFTER triggers (SECURITY DEFINER), so
  every change made through any path (API, worker, direct SQL as the
  restricted roles) is recorded with the actor taken from the verified JWT
  claims. Users can read them (owners/admins) but never write them. Metadata
  holds IDs, roles and statuses, never document text or emails.
- Rate limits use fixed windows in an internal table (works across API
  instances). Quota usage is an aggregate-only function for members.
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

UPGRADE = r"""
-- ---------------------------------------------------------------- audit logs
CREATE TABLE public.audit_logs (
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  -- No FK: audit history outlives deleted organizations and documents.
  organization_id  uuid NOT NULL,
  actor_id         uuid,
  actor_type       text NOT NULL CHECK (actor_type IN ('user', 'system')),
  action           text NOT NULL,
  resource_type    text NOT NULL,
  resource_id      uuid,
  metadata         jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX audit_logs_org_time ON public.audit_logs (organization_id, created_at DESC, id DESC);

CREATE FUNCTION app_private.write_audit(
  p_org uuid, p_action text, p_resource_type text, p_resource_id uuid, p_meta jsonb
) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  v_actor uuid := app_private.current_user_id();
BEGIN
  INSERT INTO public.audit_logs
    (organization_id, actor_id, actor_type, action, resource_type, resource_id, metadata)
  VALUES (p_org, v_actor, CASE WHEN v_actor IS NULL THEN 'system' ELSE 'user' END,
          p_action, p_resource_type, p_resource_id, coalesce(p_meta, '{}'::jsonb));
END $$;

CREATE FUNCTION app_private.audit_trigger() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  t text := TG_TABLE_NAME;
BEGIN
  IF t = 'organizations' AND TG_OP = 'INSERT' THEN
    PERFORM app_private.write_audit(NEW.id, 'organization.created', 'organization', NEW.id,
      jsonb_build_object('plan', NEW.plan));

  ELSIF t = 'organization_members' THEN
    IF TG_OP = 'INSERT' THEN
      PERFORM app_private.write_audit(NEW.organization_id, 'member.joined', 'member', NEW.id,
        jsonb_build_object('user_id', NEW.user_id, 'role', NEW.role));
    ELSIF TG_OP = 'UPDATE' THEN
      IF NEW.role IS DISTINCT FROM OLD.role THEN
        PERFORM app_private.write_audit(NEW.organization_id, 'member.role_changed', 'member',
          NEW.id, jsonb_build_object('user_id', NEW.user_id, 'from', OLD.role, 'to', NEW.role));
      END IF;
      IF NEW.status IS DISTINCT FROM OLD.status THEN
        PERFORM app_private.write_audit(NEW.organization_id,
          CASE WHEN NEW.status = 'revoked' THEN 'member.revoked' ELSE 'member.reactivated' END,
          'member', NEW.id, jsonb_build_object('user_id', NEW.user_id, 'role', NEW.role));
      END IF;
    END IF;

  ELSIF t = 'organization_invitations' THEN
    IF TG_OP = 'INSERT' THEN
      PERFORM app_private.write_audit(NEW.organization_id, 'invitation.created', 'invitation',
        NEW.id, jsonb_build_object('role', NEW.role));
    ELSIF NEW.revoked_at IS NOT NULL AND OLD.revoked_at IS NULL THEN
      PERFORM app_private.write_audit(NEW.organization_id, 'invitation.revoked', 'invitation',
        NEW.id, '{}'::jsonb);
    ELSIF NEW.accepted_at IS NOT NULL AND OLD.accepted_at IS NULL THEN
      PERFORM app_private.write_audit(NEW.organization_id, 'invitation.accepted', 'invitation',
        NEW.id, jsonb_build_object('role', NEW.role));
    END IF;

  ELSIF t = 'documents' THEN
    IF TG_OP = 'INSERT' THEN
      PERFORM app_private.write_audit(NEW.organization_id, 'document.created', 'document',
        NEW.id, jsonb_build_object('visibility', NEW.visibility));
    ELSIF TG_OP = 'UPDATE' THEN
      IF NEW.status = 'deleting' AND OLD.status <> 'deleting' THEN
        PERFORM app_private.write_audit(NEW.organization_id, 'document.deletion_requested',
          'document', NEW.id, '{}'::jsonb);
      END IF;
      IF NEW.visibility IS DISTINCT FROM OLD.visibility THEN
        PERFORM app_private.write_audit(NEW.organization_id, 'document.visibility_changed',
          'document', NEW.id, jsonb_build_object('from', OLD.visibility, 'to', NEW.visibility));
      END IF;
    ELSIF TG_OP = 'DELETE' THEN
      PERFORM app_private.write_audit(OLD.organization_id, 'document.deleted', 'document',
        OLD.id, '{}'::jsonb);
      RETURN OLD;
    END IF;

  ELSIF t = 'document_versions' THEN
    IF TG_OP = 'INSERT' THEN
      PERFORM app_private.write_audit(NEW.organization_id, 'document.version_uploaded',
        'document', NEW.document_id,
        jsonb_build_object('version_id', NEW.id, 'version', NEW.version,
                           'size_bytes', NEW.size_bytes));
    ELSIF NEW.status = 'published' AND OLD.status <> 'published' THEN
      PERFORM app_private.write_audit(NEW.organization_id, 'document.version_published',
        'document', NEW.document_id,
        jsonb_build_object('version_id', NEW.id, 'version', NEW.version));
    END IF;

  ELSIF t = 'document_permissions' THEN
    IF TG_OP = 'DELETE' THEN
      PERFORM app_private.write_audit(OLD.organization_id, 'document.permission_revoked',
        'document', OLD.document_id, jsonb_build_object('user_id', OLD.user_id));
      RETURN OLD;
    END IF;
    PERFORM app_private.write_audit(NEW.organization_id,
      CASE WHEN TG_OP = 'INSERT' THEN 'document.permission_granted'
           ELSE 'document.permission_changed' END,
      'document', NEW.document_id,
      jsonb_build_object('user_id', NEW.user_id, 'permission', NEW.permission));

  ELSIF t = 'ingestion_jobs' AND TG_OP = 'INSERT' AND NEW.kind = 'reindex' THEN
    PERFORM app_private.write_audit(NEW.organization_id, 'document.reindex_requested',
      'document', NEW.document_id, jsonb_build_object('job_id', NEW.id));
  END IF;
  RETURN coalesce(NEW, OLD);
END $$;

CREATE TRIGGER audit_organizations AFTER INSERT ON public.organizations
  FOR EACH ROW EXECUTE FUNCTION app_private.audit_trigger();
CREATE TRIGGER audit_members AFTER INSERT OR UPDATE ON public.organization_members
  FOR EACH ROW EXECUTE FUNCTION app_private.audit_trigger();
CREATE TRIGGER audit_invitations AFTER INSERT OR UPDATE ON public.organization_invitations
  FOR EACH ROW EXECUTE FUNCTION app_private.audit_trigger();
CREATE TRIGGER audit_documents AFTER INSERT OR UPDATE OR DELETE ON public.documents
  FOR EACH ROW EXECUTE FUNCTION app_private.audit_trigger();
CREATE TRIGGER audit_versions AFTER INSERT OR UPDATE OF status ON public.document_versions
  FOR EACH ROW EXECUTE FUNCTION app_private.audit_trigger();
CREATE TRIGGER audit_permissions AFTER INSERT OR UPDATE OR DELETE ON public.document_permissions
  FOR EACH ROW EXECUTE FUNCTION app_private.audit_trigger();
CREATE TRIGGER audit_jobs AFTER INSERT ON public.ingestion_jobs
  FOR EACH ROW EXECUTE FUNCTION app_private.audit_trigger();

REVOKE ALL ON public.audit_logs FROM PUBLIC, anon, authenticated;
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
    EXECUTE 'REVOKE ALL ON public.audit_logs FROM service_role';
  END IF;
END $$;
GRANT SELECT ON public.audit_logs TO authenticated;

ALTER TABLE public.audit_logs ENABLE ROW LEVEL SECURITY;
CREATE POLICY audit_select ON public.audit_logs FOR SELECT TO authenticated
  USING (app_private.member_role(organization_id) IN ('owner', 'admin'));
-- Written only by triggers; immutable for every API role.
CREATE POLICY audit_insert ON public.audit_logs FOR INSERT TO authenticated WITH CHECK (false);
CREATE POLICY audit_update ON public.audit_logs FOR UPDATE TO authenticated
  USING (false) WITH CHECK (false);
CREATE POLICY audit_delete ON public.audit_logs FOR DELETE TO authenticated USING (false);

-- ---------------------------------------------------------------- rate limits
CREATE TABLE app_private.rate_limit_counters (
  bucket        text NOT NULL,
  window_start  timestamptz NOT NULL,
  hits          integer NOT NULL,
  PRIMARY KEY (bucket, window_start)
);
ALTER TABLE app_private.rate_limit_counters ENABLE ROW LEVEL SECURITY;  -- no policies: deny all
REVOKE ALL ON app_private.rate_limit_counters FROM PUBLIC, anon, authenticated;

-- Fixed-window counter for the current user. Returns whether the call is
-- allowed and when the window resets.
CREATE FUNCTION app_private.consume_rate_limit(
  p_scope text, p_org uuid, p_limit integer, p_window_seconds integer
) RETURNS TABLE (allowed boolean, hits integer, reset_at timestamptz)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  v_uid uuid := app_private.current_user_id();
  v_window timestamptz := to_timestamp(
    floor(extract(epoch FROM now()) / p_window_seconds) * p_window_seconds);
  v_bucket text := p_scope || ':' || p_org::text || ':' || coalesce(v_uid::text, 'anonymous');
  v_hits integer;
BEGIN
  INSERT INTO app_private.rate_limit_counters AS c (bucket, window_start, hits)
    VALUES (v_bucket, v_window, 1)
  ON CONFLICT (bucket, window_start) DO UPDATE SET hits = c.hits + 1
  RETURNING c.hits INTO v_hits;
  DELETE FROM app_private.rate_limit_counters
    WHERE bucket = v_bucket AND window_start < v_window;
  RETURN QUERY SELECT v_hits <= p_limit, v_hits,
    v_window + make_interval(secs => p_window_seconds);
END $$;

-- ---------------------------------------------------------------- quota usage
-- Organization-wide aggregates (no rows, no titles) for quota checks and the
-- usage endpoint. Any active member may read them.
CREATE FUNCTION app_private.org_usage(p_org uuid, p_since timestamptz)
RETURNS TABLE (documents bigint, storage_bytes bigint, questions bigint,
               prompt_tokens bigint, completion_tokens bigint, estimated_cost numeric)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT
    (SELECT count(*) FROM public.documents d
      WHERE d.organization_id = p_org AND d.status <> 'deleting'),
    (SELECT coalesce(sum(v.size_bytes), 0)::bigint FROM public.document_versions v
      JOIN public.documents d ON d.id = v.document_id
      WHERE v.organization_id = p_org AND d.status <> 'deleting'),
    (SELECT count(*) FROM public.usage_events u
      WHERE u.organization_id = p_org AND u.kind = 'chat' AND u.created_at >= p_since),
    (SELECT coalesce(sum(u.prompt_tokens), 0)::bigint FROM public.usage_events u
      WHERE u.organization_id = p_org AND u.created_at >= p_since),
    (SELECT coalesce(sum(u.completion_tokens), 0)::bigint FROM public.usage_events u
      WHERE u.organization_id = p_org AND u.created_at >= p_since),
    (SELECT sum(u.estimated_cost) FROM public.usage_events u
      WHERE u.organization_id = p_org AND u.created_at >= p_since)
  WHERE app_private.is_member(p_org)
$$;

-- ---------------------------------------------------------------- trace context
ALTER TABLE public.ingestion_jobs ADD COLUMN trace_context jsonb;
GRANT INSERT (trace_context) ON public.ingestion_jobs TO authenticated;

REVOKE ALL ON FUNCTION app_private.write_audit(uuid, text, text, uuid, jsonb),
  app_private.audit_trigger(),
  app_private.consume_rate_limit(text, uuid, integer, integer),
  app_private.org_usage(uuid, timestamptz) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION
  app_private.consume_rate_limit(text, uuid, integer, integer),
  app_private.org_usage(uuid, timestamptz)
TO authenticated;
"""

DOWNGRADE = r"""
ALTER TABLE public.ingestion_jobs DROP COLUMN IF EXISTS trace_context;
DROP FUNCTION IF EXISTS app_private.org_usage(uuid, timestamptz);
DROP FUNCTION IF EXISTS app_private.consume_rate_limit(text, uuid, integer, integer);
DROP TABLE IF EXISTS app_private.rate_limit_counters;
DROP TRIGGER IF EXISTS audit_organizations ON public.organizations;
DROP TRIGGER IF EXISTS audit_members ON public.organization_members;
DROP TRIGGER IF EXISTS audit_invitations ON public.organization_invitations;
DROP TRIGGER IF EXISTS audit_documents ON public.documents;
DROP TRIGGER IF EXISTS audit_versions ON public.document_versions;
DROP TRIGGER IF EXISTS audit_permissions ON public.document_permissions;
DROP TRIGGER IF EXISTS audit_jobs ON public.ingestion_jobs;
DROP FUNCTION IF EXISTS app_private.audit_trigger();
DROP FUNCTION IF EXISTS app_private.write_audit(uuid, text, text, uuid, jsonb);
DROP TABLE IF EXISTS public.audit_logs;
"""


def upgrade() -> None:
    op.get_bind().connection.driver_connection.execute(UPGRADE)


def downgrade() -> None:
    op.get_bind().connection.driver_connection.execute(DOWNGRADE)
