"""Answer feedback (thumbs up/down with a reason).

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-26

- A member rates an assistant answer in their own conversation. The question
  is copied onto the feedback row so owners/admins can review it and turn it
  into an evaluation case; the answer is not copied (it derives from documents
  the reviewer may not be able to read). The UI tells users this.
- Feedback is readable by its author and by owners/admins; only the author
  can change or remove it.
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

UPGRADE = r"""
CREATE TABLE public.message_feedback (
  organization_id  uuid NOT NULL,
  message_id       uuid NOT NULL,
  user_id          uuid NOT NULL,
  rating           text NOT NULL CHECK (rating IN ('up', 'down')),
  reason           text CHECK (reason IN ('incorrect', 'missing_information', 'wrong_citation',
                                          'outdated', 'other')),
  comment          text CHECK (length(comment) <= 1000),
  question         text NOT NULL CHECK (length(question) BETWEEN 1 AND 4000),
  answer_status    text NOT NULL,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (message_id, user_id),
  FOREIGN KEY (organization_id, message_id)
    REFERENCES public.messages (organization_id, id) ON DELETE CASCADE,
  FOREIGN KEY (organization_id, user_id)
    REFERENCES public.organization_members (organization_id, user_id),
  CHECK (rating = 'down' OR reason IS NULL)
);
CREATE INDEX message_feedback_org_time
  ON public.message_feedback (organization_id, created_at DESC);

CREATE TRIGGER message_feedback_updated_at BEFORE UPDATE ON public.message_feedback
  FOR EACH ROW EXECUTE FUNCTION app_private.set_updated_at();

-- The current user owns the conversation of this assistant message.
CREATE FUNCTION app_private.owns_assistant_message(p_message uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.messages m
    JOIN public.conversations c ON c.id = m.conversation_id
    WHERE m.id = p_message AND m.role = 'assistant'
      AND c.user_id = app_private.current_user_id()
      AND app_private.is_member(c.organization_id)
  )
$$;

REVOKE ALL ON public.message_feedback FROM PUBLIC, anon, authenticated;
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
    EXECUTE 'REVOKE ALL ON public.message_feedback FROM service_role';
  END IF;
END $$;
GRANT SELECT, DELETE ON public.message_feedback TO authenticated;
GRANT INSERT (organization_id, message_id, user_id, rating, reason, comment, question,
  answer_status) ON public.message_feedback TO authenticated;
GRANT UPDATE (rating, reason, comment) ON public.message_feedback TO authenticated;

ALTER TABLE public.message_feedback ENABLE ROW LEVEL SECURITY;
CREATE POLICY feedback_select ON public.message_feedback FOR SELECT TO authenticated
  USING (
    (user_id = app_private.current_user_id() AND app_private.is_member(organization_id))
    OR app_private.is_org_admin(organization_id)
  );
CREATE POLICY feedback_insert ON public.message_feedback FOR INSERT TO authenticated
  WITH CHECK (
    user_id = app_private.current_user_id() AND app_private.owns_assistant_message(message_id)
  );
CREATE POLICY feedback_update ON public.message_feedback FOR UPDATE TO authenticated
  USING (user_id = app_private.current_user_id() AND app_private.is_member(organization_id))
  WITH CHECK (
    user_id = app_private.current_user_id() AND app_private.is_member(organization_id)
  );
CREATE POLICY feedback_delete ON public.message_feedback FOR DELETE TO authenticated
  USING (user_id = app_private.current_user_id() AND app_private.is_member(organization_id));

REVOKE ALL ON FUNCTION app_private.owns_assistant_message(uuid) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION app_private.owns_assistant_message(uuid) TO authenticated;
"""

DOWNGRADE = r"""
DROP TABLE IF EXISTS public.message_feedback;
DROP FUNCTION IF EXISTS app_private.owns_assistant_message(uuid);
"""


def upgrade() -> None:
    op.get_bind().connection.driver_connection.execute(UPGRADE)


def downgrade() -> None:
    op.get_bind().connection.driver_connection.execute(DOWNGRADE)
