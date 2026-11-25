"""In-product evaluations: datasets, cases, runs and results.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-25

- Owners and admins manage datasets and run them. A run executes as the
  requesting user, so it only ever sees documents that user can read.
- Results hold generated answers (derived from document text). A result is
  readable by the run's creator, or by another owner/admin only while every
  document the answer was generated from is readable to them. The same rule
  as stored chat answers (revocation redaction), enforced here in RLS.
- Runs and results are immutable history: no DELETE for API roles; a run's
  creator may only finish it (status, metrics, error).
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

UPGRADE = r"""
CREATE TABLE public.evaluation_datasets (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id  uuid NOT NULL REFERENCES public.organizations (id) ON DELETE CASCADE,
  name             text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
  description      text CHECK (length(description) <= 2000),
  created_by       uuid NOT NULL,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (organization_id, name),
  UNIQUE (organization_id, id),
  FOREIGN KEY (organization_id, created_by)
    REFERENCES public.organization_members (organization_id, user_id)
);

CREATE TABLE public.evaluation_cases (
  id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id        uuid NOT NULL,
  dataset_id             uuid NOT NULL,
  question               text NOT NULL CHECK (length(question) BETWEEN 1 AND 2000),
  -- Strings the answer must contain (case-insensitive).
  expected_facts         text[] NOT NULL DEFAULT '{}'
                           CHECK (cardinality(expected_facts) <= 20),
  -- Documents that should be cited. Not foreign keys: cases outlive documents.
  expected_document_ids  uuid[] NOT NULL DEFAULT '{}'
                           CHECK (cardinality(expected_document_ids) <= 20),
  should_abstain         boolean NOT NULL DEFAULT false,
  -- Insertion order (cases created in one transaction share created_at).
  seq                    bigint GENERATED ALWAYS AS IDENTITY,
  created_at             timestamptz NOT NULL DEFAULT now(),
  UNIQUE (organization_id, id),
  FOREIGN KEY (organization_id, dataset_id)
    REFERENCES public.evaluation_datasets (organization_id, id) ON DELETE CASCADE,
  CHECK (NOT (should_abstain AND cardinality(expected_facts) > 0))
);
CREATE INDEX evaluation_cases_dataset ON public.evaluation_cases (dataset_id, seq);

CREATE TABLE public.evaluation_runs (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id  uuid NOT NULL REFERENCES public.organizations (id) ON DELETE CASCADE,
  -- Runs outlive their dataset (column-list SET NULL, as for ingestion jobs).
  dataset_id       uuid,
  dataset_name     text NOT NULL,
  status           text NOT NULL DEFAULT 'running'
                     CHECK (status IN ('running', 'succeeded', 'failed')),
  config           jsonb NOT NULL DEFAULT '{}'::jsonb,
  metrics          jsonb,
  case_count       integer NOT NULL CHECK (case_count >= 0),
  error            text,
  created_by       uuid NOT NULL,
  created_at       timestamptz NOT NULL DEFAULT now(),
  finished_at      timestamptz,
  UNIQUE (organization_id, id),
  FOREIGN KEY (organization_id, dataset_id)
    REFERENCES public.evaluation_datasets (organization_id, id) ON DELETE SET NULL (dataset_id),
  FOREIGN KEY (organization_id, created_by)
    REFERENCES public.organization_members (organization_id, user_id),
  CHECK ((status = 'running') = (finished_at IS NULL))
);
CREATE INDEX evaluation_runs_org_time ON public.evaluation_runs (organization_id, created_at DESC);

CREATE TABLE public.evaluation_results (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id      uuid NOT NULL,
  run_id               uuid NOT NULL,
  case_id              uuid,
  position             integer NOT NULL CHECK (position >= 1),
  question             text NOT NULL,
  status               text NOT NULL,
  answer               text NOT NULL,
  abstained            boolean NOT NULL,
  -- NULL when the case has nothing to check for that metric.
  fact_hit             boolean,
  abstention_correct   boolean,
  evidence_hit         boolean,
  cited_document_ids   uuid[] NOT NULL DEFAULT '{}',
  -- Every document the answer was generated from (drives read access).
  source_document_ids  uuid[] NOT NULL DEFAULT '{}',
  latency_ms           integer NOT NULL CHECK (latency_ms >= 0),
  prompt_tokens        integer NOT NULL DEFAULT 0 CHECK (prompt_tokens >= 0),
  completion_tokens    integer NOT NULL DEFAULT 0 CHECK (completion_tokens >= 0),
  created_at           timestamptz NOT NULL DEFAULT now(),
  UNIQUE (run_id, position),
  FOREIGN KEY (organization_id, run_id)
    REFERENCES public.evaluation_runs (organization_id, id) ON DELETE CASCADE,
  FOREIGN KEY (organization_id, case_id)
    REFERENCES public.evaluation_cases (organization_id, id) ON DELETE SET NULL (case_id)
);

CREATE TRIGGER evaluation_datasets_updated_at BEFORE UPDATE ON public.evaluation_datasets
  FOR EACH ROW EXECUTE FUNCTION app_private.set_updated_at();

-- ---------------------------------------------------------------- helpers
CREATE FUNCTION app_private.is_org_admin(p_org uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT coalesce(app_private.member_role(p_org) IN ('owner', 'admin'), false)
$$;

-- True when the current user can read every listed document (true if none).
CREATE FUNCTION app_private.can_read_documents(p_docs uuid[]) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT coalesce(bool_and(app_private.document_access(d) IS NOT NULL), true)
  FROM unnest(p_docs) AS d
$$;

CREATE FUNCTION app_private.created_evaluation_run(p_run uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.evaluation_runs r
    WHERE r.id = p_run AND r.created_by = app_private.current_user_id()
  )
$$;

-- ---------------------------------------------------------------- privileges
REVOKE ALL ON public.evaluation_datasets, public.evaluation_cases, public.evaluation_runs,
  public.evaluation_results FROM PUBLIC, anon, authenticated;
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
    EXECUTE 'REVOKE ALL ON public.evaluation_datasets, public.evaluation_cases,
      public.evaluation_runs, public.evaluation_results FROM service_role';
  END IF;
END $$;

GRANT SELECT, DELETE ON public.evaluation_datasets TO authenticated;
GRANT INSERT (id, organization_id, name, description, created_by)
  ON public.evaluation_datasets TO authenticated;
GRANT UPDATE (name, description) ON public.evaluation_datasets TO authenticated;

GRANT SELECT, DELETE ON public.evaluation_cases TO authenticated;
GRANT INSERT (organization_id, dataset_id, question, expected_facts, expected_document_ids,
  should_abstain) ON public.evaluation_cases TO authenticated;

GRANT SELECT ON public.evaluation_runs TO authenticated;
GRANT INSERT (id, organization_id, dataset_id, dataset_name, config, case_count, created_by)
  ON public.evaluation_runs TO authenticated;
GRANT UPDATE (status, metrics, error, finished_at) ON public.evaluation_runs TO authenticated;

GRANT SELECT ON public.evaluation_results TO authenticated;
GRANT INSERT (organization_id, run_id, case_id, position, question, status, answer, abstained,
  fact_hit, abstention_correct, evidence_hit, cited_document_ids, source_document_ids,
  latency_ms, prompt_tokens, completion_tokens) ON public.evaluation_results TO authenticated;

-- ---------------------------------------------------------------- RLS
ALTER TABLE public.evaluation_datasets ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.evaluation_cases ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.evaluation_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.evaluation_results ENABLE ROW LEVEL SECURITY;

CREATE POLICY eval_datasets_select ON public.evaluation_datasets FOR SELECT TO authenticated
  USING (app_private.is_org_admin(organization_id));
CREATE POLICY eval_datasets_insert ON public.evaluation_datasets FOR INSERT TO authenticated
  WITH CHECK (
    created_by = app_private.current_user_id() AND app_private.is_org_admin(organization_id)
  );
CREATE POLICY eval_datasets_update ON public.evaluation_datasets FOR UPDATE TO authenticated
  USING (app_private.is_org_admin(organization_id))
  WITH CHECK (app_private.is_org_admin(organization_id));
CREATE POLICY eval_datasets_delete ON public.evaluation_datasets FOR DELETE TO authenticated
  USING (app_private.is_org_admin(organization_id));

CREATE POLICY eval_cases_select ON public.evaluation_cases FOR SELECT TO authenticated
  USING (app_private.is_org_admin(organization_id));
CREATE POLICY eval_cases_insert ON public.evaluation_cases FOR INSERT TO authenticated
  WITH CHECK (app_private.is_org_admin(organization_id));
CREATE POLICY eval_cases_update ON public.evaluation_cases FOR UPDATE TO authenticated
  USING (false) WITH CHECK (false);
CREATE POLICY eval_cases_delete ON public.evaluation_cases FOR DELETE TO authenticated
  USING (app_private.is_org_admin(organization_id));

CREATE POLICY eval_runs_select ON public.evaluation_runs FOR SELECT TO authenticated
  USING (app_private.is_org_admin(organization_id));
CREATE POLICY eval_runs_insert ON public.evaluation_runs FOR INSERT TO authenticated
  WITH CHECK (
    created_by = app_private.current_user_id() AND app_private.is_org_admin(organization_id)
  );
CREATE POLICY eval_runs_update ON public.evaluation_runs FOR UPDATE TO authenticated
  USING (created_by = app_private.current_user_id() AND app_private.is_org_admin(organization_id))
  WITH CHECK (
    created_by = app_private.current_user_id() AND app_private.is_org_admin(organization_id)
  );
CREATE POLICY eval_runs_delete ON public.evaluation_runs FOR DELETE TO authenticated
  USING (false);

CREATE POLICY eval_results_select ON public.evaluation_results FOR SELECT TO authenticated
  USING (
    app_private.is_org_admin(organization_id)
    AND (
      app_private.created_evaluation_run(run_id)
      OR app_private.can_read_documents(source_document_ids)
    )
  );
CREATE POLICY eval_results_insert ON public.evaluation_results FOR INSERT TO authenticated
  WITH CHECK (
    app_private.is_org_admin(organization_id) AND app_private.created_evaluation_run(run_id)
  );
CREATE POLICY eval_results_update ON public.evaluation_results FOR UPDATE TO authenticated
  USING (false) WITH CHECK (false);
CREATE POLICY eval_results_delete ON public.evaluation_results FOR DELETE TO authenticated
  USING (false);

-- Audit: dataset changes and runs (IDs and counts only).
CREATE FUNCTION app_private.audit_evaluations() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
BEGIN
  IF TG_TABLE_NAME = 'evaluation_datasets' THEN
    IF TG_OP = 'DELETE' THEN
      PERFORM app_private.write_audit(OLD.organization_id, 'evaluation.dataset_deleted',
        'evaluation_dataset', OLD.id, '{}'::jsonb);
      RETURN OLD;
    END IF;
    IF TG_OP = 'INSERT' THEN
      PERFORM app_private.write_audit(NEW.organization_id, 'evaluation.dataset_created',
        'evaluation_dataset', NEW.id, '{}'::jsonb);
    END IF;
  ELSIF TG_TABLE_NAME = 'evaluation_runs' AND TG_OP = 'INSERT' THEN
    PERFORM app_private.write_audit(NEW.organization_id, 'evaluation.run_started',
      'evaluation_run', NEW.id,
      jsonb_build_object('dataset_id', NEW.dataset_id, 'case_count', NEW.case_count));
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER audit_evaluation_datasets AFTER INSERT OR DELETE ON public.evaluation_datasets
  FOR EACH ROW EXECUTE FUNCTION app_private.audit_evaluations();
CREATE TRIGGER audit_evaluation_runs AFTER INSERT ON public.evaluation_runs
  FOR EACH ROW EXECUTE FUNCTION app_private.audit_evaluations();

REVOKE ALL ON FUNCTION app_private.is_org_admin(uuid), app_private.can_read_documents(uuid[]),
  app_private.created_evaluation_run(uuid), app_private.audit_evaluations() FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION app_private.is_org_admin(uuid), app_private.can_read_documents(uuid[]),
  app_private.created_evaluation_run(uuid) TO authenticated;
"""

DOWNGRADE = r"""
DROP TABLE IF EXISTS public.evaluation_results, public.evaluation_runs,
  public.evaluation_cases, public.evaluation_datasets;
DROP FUNCTION IF EXISTS app_private.audit_evaluations();
DROP FUNCTION IF EXISTS app_private.created_evaluation_run(uuid);
DROP FUNCTION IF EXISTS app_private.can_read_documents(uuid[]);
DROP FUNCTION IF EXISTS app_private.is_org_admin(uuid);
"""


def upgrade() -> None:
    op.get_bind().connection.driver_connection.execute(UPGRADE)


def downgrade() -> None:
    op.get_bind().connection.driver_connection.execute(DOWNGRADE)
