"""Allow the agent's response statuses on assistant messages.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-25
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().connection.driver_connection.execute(
        """
        ALTER TABLE public.messages DROP CONSTRAINT messages_status_check;
        ALTER TABLE public.messages ADD CONSTRAINT messages_status_check CHECK (
          status IN ('answered', 'insufficient_evidence', 'clarification_needed', 'direct', 'error')
        );
        """
    )


def downgrade() -> None:
    op.get_bind().connection.driver_connection.execute(
        """
        UPDATE public.messages SET status = 'answered'
          WHERE status IN ('clarification_needed', 'direct');
        ALTER TABLE public.messages DROP CONSTRAINT messages_status_check;
        ALTER TABLE public.messages ADD CONSTRAINT messages_status_check CHECK (
          status IN ('answered', 'insufficient_evidence', 'error')
        );
        """
    )
