"""Documents, versions, permissions, chunks and the ingestion job queue.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-25

Security model additions (see docs/decisions/0005-ingestion-pipeline.md):
- Document access is decided in Postgres by app_private.document_access():
  restricted documents need ownership or an explicit permission row, whatever
  the member's org role ("document ACLs apply independently"). Viewers never write.
- The worker logs in as `atlas_worker` (NOBYPASSRLS). For each job it sets
  `app.organization_id`, and its policies only match rows of that tenant.
  Jobs are claimed through a SECURITY DEFINER function using SKIP LOCKED.
- Storage paths are tenant-scoped and enforced by a CHECK constraint.
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

UPGRADE = r"""
-- ---------------------------------------------------------------- worker role
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'atlas_worker') THEN
    CREATE ROLE atlas_worker NOLOGIN NOINHERIT NOCREATEDB NOCREATEROLE NOBYPASSRLS;
  END IF;
END $$;
GRANT CONNECT ON DATABASE current_database_placeholder TO atlas_worker;
GRANT USAGE ON SCHEMA app_private TO atlas_worker;

-- Tenant the worker is processing right now (set per job, transaction-local).
CREATE FUNCTION app_private.worker_org() RETURNS uuid
LANGUAGE sql STABLE SET search_path = '' AS $$
  SELECT nullif(current_setting('app.organization_id', true), '')::uuid
$$;

-- ---------------------------------------------------------------- tables
CREATE TABLE public.documents (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id     uuid NOT NULL REFERENCES public.organizations (id) ON DELETE CASCADE,
  owner_id            uuid NOT NULL,
  title               text NOT NULL CHECK (length(btrim(title)) BETWEEN 1 AND 300),
  visibility          text NOT NULL DEFAULT 'organization'
                        CHECK (visibility IN ('organization', 'restricted')),
  status              text NOT NULL DEFAULT 'processing'
                        CHECK (status IN ('processing', 'ready', 'failed', 'deleting')),
  current_version_id  uuid,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  UNIQUE (organization_id, id),
  FOREIGN KEY (organization_id, owner_id)
    REFERENCES public.organization_members (organization_id, user_id)
);

CREATE TABLE public.document_versions (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id  uuid NOT NULL,
  document_id      uuid NOT NULL,
  version          integer NOT NULL CHECK (version >= 1),
  filename         text NOT NULL CHECK (length(filename) BETWEEN 1 AND 255),
  mime_type        text NOT NULL,
  size_bytes       bigint NOT NULL CHECK (size_bytes > 0),
  checksum         text NOT NULL CHECK (checksum ~ '^[0-9a-f]{64}$'),
  storage_path     text NOT NULL,
  effective_date   date,
  status           text NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'processing', 'published', 'superseded',
                                       'failed')),
  chunk_count      integer CHECK (chunk_count >= 0),
  error            text,
  created_by       uuid NOT NULL,
  created_at       timestamptz NOT NULL DEFAULT now(),
  published_at     timestamptz,
  UNIQUE (document_id, version),
  UNIQUE (organization_id, id),
  UNIQUE (organization_id, document_id, id),
  FOREIGN KEY (organization_id, document_id)
    REFERENCES public.documents (organization_id, id) ON DELETE CASCADE,
  -- Files live under <org>/<document>/<version>/ and nowhere else.
  CHECK (storage_path LIKE organization_id::text || '/' || document_id::text || '/'
                           || id::text || '/%'),
  CHECK ((status = 'published') = (published_at IS NOT NULL) OR status = 'superseded')
);
CREATE INDEX document_versions_checksum ON public.document_versions (organization_id, checksum);
CREATE UNIQUE INDEX document_versions_one_published ON public.document_versions (document_id)
  WHERE status = 'published';

-- The published version must belong to the same document and tenant.
ALTER TABLE public.documents ADD FOREIGN KEY (organization_id, id, current_version_id)
  REFERENCES public.document_versions (organization_id, document_id, id);

CREATE TABLE public.document_permissions (
  organization_id  uuid NOT NULL,
  document_id      uuid NOT NULL,
  user_id          uuid NOT NULL,
  permission       text NOT NULL CHECK (permission IN ('read', 'write')),
  granted_by       uuid NOT NULL,
  created_at       timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (document_id, user_id),
  FOREIGN KEY (organization_id, document_id)
    REFERENCES public.documents (organization_id, id) ON DELETE CASCADE,
  FOREIGN KEY (organization_id, user_id)
    REFERENCES public.organization_members (organization_id, user_id),
  FOREIGN KEY (organization_id, granted_by)
    REFERENCES public.organization_members (organization_id, user_id)
);

CREATE TABLE public.document_chunks (
  -- Deterministic (uuid5 of version + index) and identical to the Qdrant point ID.
  id                   uuid PRIMARY KEY,
  organization_id      uuid NOT NULL,
  document_id          uuid NOT NULL,
  document_version_id  uuid NOT NULL,
  chunk_index          integer NOT NULL CHECK (chunk_index >= 0),
  content              text NOT NULL,
  token_count          integer NOT NULL CHECK (token_count > 0),
  page_start           integer CHECK (page_start >= 1),
  page_end             integer CHECK (page_end >= page_start),
  section              text,
  embedding_status     text NOT NULL DEFAULT 'pending'
                         CHECK (embedding_status IN ('pending', 'indexed')),
  created_at           timestamptz NOT NULL DEFAULT now(),
  UNIQUE (document_version_id, chunk_index),
  FOREIGN KEY (organization_id, document_id, document_version_id)
    REFERENCES public.document_versions (organization_id, document_id, id) ON DELETE CASCADE
);
CREATE INDEX document_chunks_document ON public.document_chunks (organization_id, document_id);

CREATE TABLE public.ingestion_jobs (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id      uuid NOT NULL REFERENCES public.organizations (id) ON DELETE CASCADE,
  document_id          uuid,
  document_version_id  uuid,
  kind                 text NOT NULL CHECK (kind IN ('ingest', 'reindex', 'delete')),
  status               text NOT NULL DEFAULT 'queued'
                         CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
  idempotency_key      text NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 200),
  attempts             integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  max_attempts         integer NOT NULL DEFAULT 5 CHECK (max_attempts BETWEEN 1 AND 20),
  run_after            timestamptz NOT NULL DEFAULT now(),
  locked_at            timestamptz,
  locked_by            text,
  last_error           text,
  created_by           uuid NOT NULL,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  finished_at          timestamptz,
  UNIQUE (organization_id, idempotency_key),
  -- Job history outlives deleted documents (PG15 column-list SET NULL).
  FOREIGN KEY (organization_id, document_id)
    REFERENCES public.documents (organization_id, id) ON DELETE SET NULL (document_id),
  FOREIGN KEY (organization_id, document_version_id)
    REFERENCES public.document_versions (organization_id, id)
    ON DELETE SET NULL (document_version_id)
);
CREATE INDEX ingestion_jobs_ready ON public.ingestion_jobs (run_after) WHERE status = 'queued';
-- At most one active (re)index job per version and one delete job per document.
CREATE UNIQUE INDEX ingestion_jobs_one_active_index ON public.ingestion_jobs (document_version_id)
  WHERE status IN ('queued', 'running') AND kind IN ('ingest', 'reindex');
CREATE UNIQUE INDEX ingestion_jobs_one_active_delete ON public.ingestion_jobs (document_id)
  WHERE status IN ('queued', 'running') AND kind = 'delete';

CREATE TRIGGER documents_updated_at BEFORE UPDATE ON public.documents
  FOR EACH ROW EXECUTE FUNCTION app_private.set_updated_at();
CREATE TRIGGER ingestion_jobs_updated_at BEFORE UPDATE ON public.ingestion_jobs
  FOR EACH ROW EXECUTE FUNCTION app_private.set_updated_at();

-- ---------------------------------------------------------------- access helpers
CREATE FUNCTION app_private.has_document_permission(p_doc uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.document_permissions p
    WHERE p.document_id = p_doc AND p.user_id = app_private.current_user_id()
  )
$$;

-- 'write', 'read' or NULL for the current user. Org role never overrides a
-- restricted document's ACL; viewers are capped at read.
CREATE FUNCTION app_private.document_access(p_doc uuid) RETURNS text
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  v_uid  uuid := app_private.current_user_id();
  v_doc  record;
  v_role text;
  v_perm text;
BEGIN
  SELECT organization_id, owner_id, visibility INTO v_doc
    FROM public.documents WHERE id = p_doc;
  IF NOT FOUND THEN
    RETURN NULL;
  END IF;
  v_role := app_private.member_role(v_doc.organization_id);
  IF v_role IS NULL THEN
    RETURN NULL;
  END IF;
  SELECT permission INTO v_perm FROM public.document_permissions
    WHERE document_id = p_doc AND user_id = v_uid;
  IF v_doc.visibility = 'restricted' AND v_doc.owner_id <> v_uid AND v_perm IS NULL THEN
    RETURN NULL;
  END IF;
  IF v_role = 'viewer' THEN
    RETURN 'read';
  END IF;
  IF v_doc.owner_id = v_uid OR v_perm = 'write' THEN
    RETURN 'write';
  END IF;
  IF v_doc.visibility = 'organization' AND v_role IN ('owner', 'admin') THEN
    RETURN 'write';
  END IF;
  RETURN 'read';
END $$;

-- ---------------------------------------------------------------- privileges
REVOKE ALL ON public.documents, public.document_versions, public.document_permissions,
  public.document_chunks, public.ingestion_jobs FROM PUBLIC, anon, authenticated;
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
    EXECUTE 'REVOKE ALL ON public.documents, public.document_versions,
      public.document_permissions, public.document_chunks, public.ingestion_jobs
      FROM service_role';
  END IF;
END $$;

-- authenticated (API requests)
GRANT SELECT ON public.documents TO authenticated;
GRANT INSERT (id, organization_id, owner_id, title, visibility)
  ON public.documents TO authenticated;
GRANT UPDATE (title, visibility) ON public.documents TO authenticated;

GRANT SELECT ON public.document_versions TO authenticated;
GRANT INSERT (id, organization_id, document_id, version, filename, mime_type, size_bytes,
  checksum, storage_path, effective_date, created_by) ON public.document_versions TO authenticated;

GRANT SELECT, DELETE ON public.document_permissions TO authenticated;
GRANT INSERT (organization_id, document_id, user_id, permission, granted_by)
  ON public.document_permissions TO authenticated;
GRANT UPDATE (permission) ON public.document_permissions TO authenticated;

GRANT SELECT ON public.document_chunks TO authenticated;

GRANT SELECT ON public.ingestion_jobs TO authenticated;
GRANT INSERT (organization_id, document_id, document_version_id, kind, idempotency_key,
  max_attempts, created_by) ON public.ingestion_jobs TO authenticated;

-- atlas_worker (ingestion)
GRANT SELECT, DELETE ON public.documents TO atlas_worker;
GRANT UPDATE (status, current_version_id) ON public.documents TO atlas_worker;
GRANT SELECT ON public.document_versions TO atlas_worker;
GRANT UPDATE (status, chunk_count, error, published_at, effective_date)
  ON public.document_versions TO atlas_worker;
GRANT SELECT, INSERT, DELETE ON public.document_chunks TO atlas_worker;
GRANT UPDATE (embedding_status) ON public.document_chunks TO atlas_worker;
GRANT SELECT ON public.ingestion_jobs TO atlas_worker;
GRANT UPDATE (status, run_after, locked_at, locked_by, last_error, finished_at)
  ON public.ingestion_jobs TO atlas_worker;

-- ---------------------------------------------------------------- RLS
ALTER TABLE public.documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.document_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.document_permissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.document_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ingestion_jobs ENABLE ROW LEVEL SECURITY;

-- documents (inline checks so INSERT ... RETURNING sees the new row)
CREATE POLICY documents_select ON public.documents FOR SELECT TO authenticated
  USING (
    app_private.is_member(organization_id)
    AND (
      visibility = 'organization'
      OR owner_id = app_private.current_user_id()
      OR app_private.has_document_permission(id)
    )
  );
CREATE POLICY documents_insert ON public.documents FOR INSERT TO authenticated
  WITH CHECK (
    owner_id = app_private.current_user_id()
    AND app_private.member_role(organization_id) IN ('owner', 'admin', 'member')
  );
CREATE POLICY documents_update ON public.documents FOR UPDATE TO authenticated
  USING (app_private.document_access(id) = 'write')
  WITH CHECK (app_private.document_access(id) = 'write');
-- Deletion is a job: API marks the document 'deleting', the worker removes it.
CREATE POLICY documents_delete ON public.documents FOR DELETE TO authenticated
  USING (false);

-- document_versions
CREATE POLICY versions_select ON public.document_versions FOR SELECT TO authenticated
  USING (app_private.document_access(document_id) IS NOT NULL);
CREATE POLICY versions_insert ON public.document_versions FOR INSERT TO authenticated
  WITH CHECK (
    created_by = app_private.current_user_id()
    AND app_private.document_access(document_id) = 'write'
  );
CREATE POLICY versions_update ON public.document_versions FOR UPDATE TO authenticated
  USING (false) WITH CHECK (false);
CREATE POLICY versions_delete ON public.document_versions FOR DELETE TO authenticated
  USING (false);

-- document_permissions
CREATE POLICY permissions_select ON public.document_permissions FOR SELECT TO authenticated
  USING (
    (user_id = app_private.current_user_id() AND app_private.is_member(organization_id))
    OR app_private.document_access(document_id) = 'write'
  );
CREATE POLICY permissions_insert ON public.document_permissions FOR INSERT TO authenticated
  WITH CHECK (
    granted_by = app_private.current_user_id()
    AND app_private.document_access(document_id) = 'write'
  );
CREATE POLICY permissions_update ON public.document_permissions FOR UPDATE TO authenticated
  USING (app_private.document_access(document_id) = 'write')
  WITH CHECK (app_private.document_access(document_id) = 'write');
CREATE POLICY permissions_delete ON public.document_permissions FOR DELETE TO authenticated
  USING (app_private.document_access(document_id) = 'write');

-- document_chunks (written only by the worker)
CREATE POLICY chunks_select ON public.document_chunks FOR SELECT TO authenticated
  USING (app_private.document_access(document_id) IS NOT NULL);
CREATE POLICY chunks_insert ON public.document_chunks FOR INSERT TO authenticated
  WITH CHECK (false);
CREATE POLICY chunks_update ON public.document_chunks FOR UPDATE TO authenticated
  USING (false) WITH CHECK (false);
CREATE POLICY chunks_delete ON public.document_chunks FOR DELETE TO authenticated
  USING (false);

-- ingestion_jobs
CREATE POLICY jobs_select ON public.ingestion_jobs FOR SELECT TO authenticated
  USING (
    app_private.is_member(organization_id)
    AND (
      created_by = app_private.current_user_id()
      OR (document_id IS NOT NULL AND app_private.document_access(document_id) IS NOT NULL)
    )
  );
CREATE POLICY jobs_insert ON public.ingestion_jobs FOR INSERT TO authenticated
  WITH CHECK (
    created_by = app_private.current_user_id()
    AND document_id IS NOT NULL
    AND app_private.document_access(document_id) = 'write'
  );
CREATE POLICY jobs_update ON public.ingestion_jobs FOR UPDATE TO authenticated
  USING (false) WITH CHECK (false);
CREATE POLICY jobs_delete ON public.ingestion_jobs FOR DELETE TO authenticated
  USING (false);

-- worker: every policy is pinned to the tenant of the job being processed
CREATE POLICY documents_worker_select ON public.documents FOR SELECT TO atlas_worker
  USING (organization_id = app_private.worker_org());
CREATE POLICY documents_worker_update ON public.documents FOR UPDATE TO atlas_worker
  USING (organization_id = app_private.worker_org())
  WITH CHECK (organization_id = app_private.worker_org());
CREATE POLICY documents_worker_delete ON public.documents FOR DELETE TO atlas_worker
  USING (organization_id = app_private.worker_org() AND status = 'deleting');

CREATE POLICY versions_worker_select ON public.document_versions FOR SELECT TO atlas_worker
  USING (organization_id = app_private.worker_org());
CREATE POLICY versions_worker_update ON public.document_versions FOR UPDATE TO atlas_worker
  USING (organization_id = app_private.worker_org())
  WITH CHECK (organization_id = app_private.worker_org());

CREATE POLICY chunks_worker_select ON public.document_chunks FOR SELECT TO atlas_worker
  USING (organization_id = app_private.worker_org());
CREATE POLICY chunks_worker_insert ON public.document_chunks FOR INSERT TO atlas_worker
  WITH CHECK (organization_id = app_private.worker_org());
CREATE POLICY chunks_worker_update ON public.document_chunks FOR UPDATE TO atlas_worker
  USING (organization_id = app_private.worker_org())
  WITH CHECK (organization_id = app_private.worker_org());
CREATE POLICY chunks_worker_delete ON public.document_chunks FOR DELETE TO atlas_worker
  USING (organization_id = app_private.worker_org());

CREATE POLICY jobs_worker_select ON public.ingestion_jobs FOR SELECT TO atlas_worker
  USING (organization_id = app_private.worker_org());
CREATE POLICY jobs_worker_update ON public.ingestion_jobs FOR UPDATE TO atlas_worker
  USING (organization_id = app_private.worker_org())
  WITH CHECK (organization_id = app_private.worker_org());

-- ---------------------------------------------------------------- definer entry points
-- Mark a document for deletion if the current user may write it.
CREATE FUNCTION app_private.mark_document_deleting(p_doc uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
BEGIN
  IF app_private.document_access(p_doc) IS DISTINCT FROM 'write' THEN
    RETURN false;
  END IF;
  UPDATE public.documents SET status = 'deleting' WHERE id = p_doc;
  RETURN true;
END $$;

-- Claim the next runnable job across all tenants (queued and due, or running
-- with an expired lease). Returns only queue metadata, never document content.
CREATE FUNCTION app_private.claim_ingestion_job(p_worker text, p_lease_seconds integer)
RETURNS SETOF public.ingestion_jobs
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = '' AS $$
  UPDATE public.ingestion_jobs j
     SET status = 'running', attempts = j.attempts + 1, locked_at = now(), locked_by = p_worker
   WHERE j.id = (
     SELECT q.id FROM public.ingestion_jobs q
      WHERE (q.status = 'queued' AND q.run_after <= now())
         OR (q.status = 'running'
             AND q.locked_at < now() - make_interval(secs => p_lease_seconds))
      ORDER BY q.run_after, q.created_at
      FOR UPDATE SKIP LOCKED
      LIMIT 1
   )
  RETURNING j.*
$$;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA app_private FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION
  app_private.has_document_permission(uuid),
  app_private.document_access(uuid),
  app_private.mark_document_deleting(uuid)
TO authenticated;
GRANT EXECUTE ON FUNCTION
  app_private.worker_org(),
  app_private.claim_ingestion_job(text, integer)
TO atlas_worker;
"""

DOWNGRADE = r"""
DROP FUNCTION IF EXISTS app_private.claim_ingestion_job(text, integer);
DROP FUNCTION IF EXISTS app_private.mark_document_deleting(uuid);
-- One statement drops the documents <-> document_versions FK cycle together.
DROP TABLE IF EXISTS public.ingestion_jobs, public.document_chunks,
  public.document_permissions, public.document_versions, public.documents;
DROP FUNCTION IF EXISTS app_private.document_access(uuid);
DROP FUNCTION IF EXISTS app_private.has_document_permission(uuid);
DROP FUNCTION IF EXISTS app_private.worker_org();
REVOKE USAGE ON SCHEMA app_private FROM atlas_worker;
REVOKE CONNECT ON DATABASE current_database_placeholder FROM atlas_worker;
-- The atlas_worker role is cluster-wide and kept.
"""


def _run(sql: str) -> None:
    raw = op.get_bind().connection.driver_connection
    (db,) = raw.execute("SELECT current_database()").fetchone()
    quoted = '"' + db.replace('"', '""') + '"'
    raw.execute(sql.replace("current_database_placeholder", quoted))


def upgrade() -> None:
    _run(UPGRADE)


def downgrade() -> None:
    _run(DOWNGRADE)
