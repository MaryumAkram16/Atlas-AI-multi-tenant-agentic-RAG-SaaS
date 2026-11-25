"""Conversations, messages, citations and usage events.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-25

- Conversations are private to the user who started them, and only while
  they are an active member of the organization.
- A citation is only visible while its document is still readable by the
  viewer (document_access), so revoked or restricted sources disappear from
  stored answers automatically.
- Citations reference document versions (cascade on delete) but not chunk
  rows, because reindexing rewrites chunks with the same deterministic IDs.
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

UPGRADE = r"""
CREATE TABLE public.conversations (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id  uuid NOT NULL REFERENCES public.organizations (id) ON DELETE CASCADE,
  user_id          uuid NOT NULL,
  title            text NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (organization_id, id),
  FOREIGN KEY (organization_id, user_id)
    REFERENCES public.organization_members (organization_id, user_id)
);
CREATE INDEX conversations_user ON public.conversations (organization_id, user_id, updated_at DESC);

CREATE TABLE public.messages (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id  uuid NOT NULL,
  conversation_id  uuid NOT NULL,
  role             text NOT NULL CHECK (role IN ('user', 'assistant')),
  content          text NOT NULL CHECK (length(content) <= 20000),
  status           text CHECK (status IN ('answered', 'insufficient_evidence', 'error')),
  metadata         jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (organization_id, id),
  FOREIGN KEY (organization_id, conversation_id)
    REFERENCES public.conversations (organization_id, id) ON DELETE CASCADE,
  CHECK ((role = 'assistant') = (status IS NOT NULL))
);
CREATE INDEX messages_conversation ON public.messages (conversation_id, created_at);

CREATE TABLE public.message_citations (
  organization_id      uuid NOT NULL,
  message_id           uuid NOT NULL,
  position             integer NOT NULL CHECK (position >= 1),
  document_id          uuid NOT NULL,
  document_version_id  uuid NOT NULL,
  chunk_id             uuid NOT NULL,
  page_start           integer,
  page_end             integer,
  section              text,
  PRIMARY KEY (message_id, position),
  FOREIGN KEY (organization_id, message_id)
    REFERENCES public.messages (organization_id, id) ON DELETE CASCADE,
  FOREIGN KEY (organization_id, document_id, document_version_id)
    REFERENCES public.document_versions (organization_id, document_id, id) ON DELETE CASCADE
);
CREATE INDEX message_citations_document ON public.message_citations (document_id);

CREATE TABLE public.usage_events (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id    uuid NOT NULL REFERENCES public.organizations (id) ON DELETE CASCADE,
  user_id            uuid NOT NULL,
  message_id         uuid,
  kind               text NOT NULL CHECK (kind IN ('chat', 'embedding')),
  model              text NOT NULL,
  prompt_tokens      integer NOT NULL DEFAULT 0 CHECK (prompt_tokens >= 0),
  completion_tokens  integer NOT NULL DEFAULT 0 CHECK (completion_tokens >= 0),
  -- NULL when no price is configured; never guessed.
  estimated_cost     numeric(12, 6) CHECK (estimated_cost >= 0),
  created_at         timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (organization_id, user_id)
    REFERENCES public.organization_members (organization_id, user_id),
  FOREIGN KEY (organization_id, message_id)
    REFERENCES public.messages (organization_id, id) ON DELETE SET NULL (message_id)
);
CREATE INDEX usage_events_org_time ON public.usage_events (organization_id, created_at);

CREATE TRIGGER conversations_updated_at BEFORE UPDATE ON public.conversations
  FOR EACH ROW EXECUTE FUNCTION app_private.set_updated_at();

-- ---------------------------------------------------------------- helpers
CREATE FUNCTION app_private.owns_conversation(p_conversation uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.conversations c
    WHERE c.id = p_conversation
      AND c.user_id = app_private.current_user_id()
      AND app_private.is_member(c.organization_id)
  )
$$;

-- ---------------------------------------------------------------- privileges
REVOKE ALL ON public.conversations, public.messages, public.message_citations,
  public.usage_events FROM PUBLIC, anon, authenticated;
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
    EXECUTE 'REVOKE ALL ON public.conversations, public.messages,
      public.message_citations, public.usage_events FROM service_role';
  END IF;
END $$;

GRANT SELECT, DELETE ON public.conversations TO authenticated;
GRANT INSERT (id, organization_id, user_id, title) ON public.conversations TO authenticated;
GRANT UPDATE (title) ON public.conversations TO authenticated;

GRANT SELECT ON public.messages TO authenticated;
GRANT INSERT (id, organization_id, conversation_id, role, content, status, metadata)
  ON public.messages TO authenticated;

GRANT SELECT ON public.message_citations TO authenticated;
GRANT INSERT (organization_id, message_id, position, document_id, document_version_id,
  chunk_id, page_start, page_end, section) ON public.message_citations TO authenticated;

GRANT SELECT ON public.usage_events TO authenticated;
GRANT INSERT (organization_id, user_id, message_id, kind, model, prompt_tokens,
  completion_tokens, estimated_cost) ON public.usage_events TO authenticated;

-- ---------------------------------------------------------------- RLS
ALTER TABLE public.conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.message_citations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.usage_events ENABLE ROW LEVEL SECURITY;

-- conversations: private to their author, while a member
CREATE POLICY conversations_select ON public.conversations FOR SELECT TO authenticated
  USING (user_id = app_private.current_user_id() AND app_private.is_member(organization_id));
CREATE POLICY conversations_insert ON public.conversations FOR INSERT TO authenticated
  WITH CHECK (
    user_id = app_private.current_user_id() AND app_private.is_member(organization_id)
  );
CREATE POLICY conversations_update ON public.conversations FOR UPDATE TO authenticated
  USING (user_id = app_private.current_user_id() AND app_private.is_member(organization_id))
  WITH CHECK (
    user_id = app_private.current_user_id() AND app_private.is_member(organization_id)
  );
CREATE POLICY conversations_delete ON public.conversations FOR DELETE TO authenticated
  USING (user_id = app_private.current_user_id() AND app_private.is_member(organization_id));

-- messages: visible/insertable only inside one's own conversation; immutable
CREATE POLICY messages_select ON public.messages FOR SELECT TO authenticated
  USING (app_private.owns_conversation(conversation_id));
CREATE POLICY messages_insert ON public.messages FOR INSERT TO authenticated
  WITH CHECK (app_private.owns_conversation(conversation_id));
CREATE POLICY messages_update ON public.messages FOR UPDATE TO authenticated
  USING (false) WITH CHECK (false);
CREATE POLICY messages_delete ON public.messages FOR DELETE TO authenticated
  USING (false);

-- citations: own message AND the cited document is still readable now
CREATE POLICY citations_select ON public.message_citations FOR SELECT TO authenticated
  USING (
    EXISTS (SELECT 1 FROM public.messages m WHERE m.id = message_id)
    AND app_private.document_access(document_id) IS NOT NULL
  );
CREATE POLICY citations_insert ON public.message_citations FOR INSERT TO authenticated
  WITH CHECK (
    EXISTS (SELECT 1 FROM public.messages m WHERE m.id = message_id)
    AND app_private.document_access(document_id) IS NOT NULL
  );
CREATE POLICY citations_update ON public.message_citations FOR UPDATE TO authenticated
  USING (false) WITH CHECK (false);
CREATE POLICY citations_delete ON public.message_citations FOR DELETE TO authenticated
  USING (false);

-- usage: own events; owners/admins see the whole organization's usage
CREATE POLICY usage_select ON public.usage_events FOR SELECT TO authenticated
  USING (
    (user_id = app_private.current_user_id() AND app_private.is_member(organization_id))
    OR app_private.member_role(organization_id) IN ('owner', 'admin')
  );
CREATE POLICY usage_insert ON public.usage_events FOR INSERT TO authenticated
  WITH CHECK (
    user_id = app_private.current_user_id() AND app_private.is_member(organization_id)
  );
CREATE POLICY usage_update ON public.usage_events FOR UPDATE TO authenticated
  USING (false) WITH CHECK (false);
CREATE POLICY usage_delete ON public.usage_events FOR DELETE TO authenticated
  USING (false);

REVOKE ALL ON FUNCTION app_private.owns_conversation(uuid) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION app_private.owns_conversation(uuid) TO authenticated;
"""

DOWNGRADE = r"""
DROP TABLE IF EXISTS public.usage_events, public.message_citations, public.messages,
  public.conversations;
DROP FUNCTION IF EXISTS app_private.owns_conversation(uuid);
"""


def upgrade() -> None:
    op.get_bind().connection.driver_connection.execute(UPGRADE)


def downgrade() -> None:
    op.get_bind().connection.driver_connection.execute(DOWNGRADE)
