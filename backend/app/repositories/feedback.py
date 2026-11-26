"""Answer feedback data access (inside UserDB transactions; RLS applies)."""

from typing import Any
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import dict_row

Row = dict[str, Any]


async def _all(conn: AsyncConnection, query: str, params: tuple) -> list[Row]:
    cur = conn.cursor(row_factory=dict_row)
    await cur.execute(query, params)
    return await cur.fetchall()


async def assistant_message(
    conn: AsyncConnection, org_id: UUID, conv_id: UUID, message_id: UUID
) -> Row | None:
    """The assistant message and the question it answered (messages RLS: own chats)."""
    rows = await _all(
        conn,
        """
        SELECT a.id, a.status,
               (SELECT u.content FROM messages u
                WHERE u.conversation_id = a.conversation_id AND u.role = 'user'
                  AND (u.created_at, u.id) < (a.created_at, a.id)
                ORDER BY u.created_at DESC, u.id DESC LIMIT 1) AS question
        FROM messages a
        WHERE a.organization_id = %s AND a.conversation_id = %s AND a.id = %s
          AND a.role = 'assistant'
        """,
        (org_id, conv_id, message_id),
    )
    return rows[0] if rows else None


async def upsert(
    conn: AsyncConnection,
    *,
    org_id: UUID,
    message_id: UUID,
    user_id: UUID,
    rating: str,
    reason: str | None,
    comment: str | None,
    question: str,
    answer_status: str,
) -> Row:
    rows = await _all(
        conn,
        """
        INSERT INTO message_feedback (organization_id, message_id, user_id, rating, reason,
            comment, question, answer_status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (message_id, user_id) DO UPDATE
          SET rating = EXCLUDED.rating, reason = EXCLUDED.reason, comment = EXCLUDED.comment
        RETURNING message_id, rating, reason, comment, created_at, updated_at
        """,
        (org_id, message_id, user_id, rating, reason, comment, question, answer_status),
    )
    return rows[0]


async def delete(conn: AsyncConnection, org_id: UUID, message_id: UUID, user_id: UUID) -> bool:
    cur = await conn.execute(
        "DELETE FROM message_feedback WHERE organization_id = %s AND message_id = %s"
        " AND user_id = %s",
        (org_id, message_id, user_id),
    )
    return cur.rowcount > 0


async def own_feedback(
    conn: AsyncConnection, message_ids: list[UUID], user_id: UUID
) -> dict[UUID, Row]:
    if not message_ids:
        return {}
    rows = await _all(
        conn,
        """
        SELECT message_id, rating, reason, comment, created_at, updated_at
        FROM message_feedback WHERE message_id = ANY(%s) AND user_id = %s
        """,
        (message_ids, user_id),
    )
    return {r["message_id"]: r for r in rows}


async def review(conn: AsyncConnection, org_id: UUID, rating: str | None, limit: int) -> list[Row]:
    """Owners/admins (RLS): feedback across the workspace, newest first."""
    return await _all(
        conn,
        """
        SELECT f.message_id, f.user_id, m.email, f.rating, f.reason, f.comment, f.question,
               f.answer_status, f.created_at, f.updated_at
        FROM message_feedback f
        LEFT JOIN organization_members m
          ON m.organization_id = f.organization_id AND m.user_id = f.user_id
        WHERE f.organization_id = %s AND (%s::text IS NULL OR f.rating = %s)
        ORDER BY f.created_at DESC
        LIMIT %s
        """,
        (org_id, rating, rating, limit),
    )
