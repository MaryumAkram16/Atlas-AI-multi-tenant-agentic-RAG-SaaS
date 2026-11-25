"""Conversation data access (inside UserDB transactions; RLS applies)."""

import json
from decimal import Decimal
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import dict_row

Row = dict[str, Any]


async def _all(conn: AsyncConnection, query: str, params: tuple) -> list[Row]:
    cur = conn.cursor(row_factory=dict_row)
    await cur.execute(query, params)
    return await cur.fetchall()


async def _one(conn: AsyncConnection, query: str, params: tuple) -> Row | None:
    rows = await _all(conn, query, params)
    return rows[0] if rows else None


async def get_conversation(conn: AsyncConnection, org_id: UUID, conv_id: UUID) -> Row | None:
    return await _one(
        conn,
        """
        SELECT id, title, created_at, updated_at FROM conversations
        WHERE organization_id = %s AND id = %s
        """,
        (org_id, conv_id),
    )


async def list_conversations(conn: AsyncConnection, org_id: UUID, user_id: UUID) -> list[Row]:
    return await _all(
        conn,
        """
        SELECT id, title, created_at, updated_at FROM conversations
        WHERE organization_id = %s AND user_id = %s
        ORDER BY updated_at DESC, id
        LIMIT 100
        """,
        (org_id, user_id),
    )


async def create_conversation(
    conn: AsyncConnection, conv_id: UUID, org_id: UUID, user_id: UUID, title: str
) -> None:
    await conn.execute(
        "INSERT INTO conversations (id, organization_id, user_id, title) VALUES (%s, %s, %s, %s)",
        (conv_id, org_id, user_id, title),
    )


async def touch_conversation(conn: AsyncConnection, conv_id: UUID) -> None:
    await conn.execute("UPDATE conversations SET title = title WHERE id = %s", (conv_id,))


async def recent_messages(conn: AsyncConnection, conv_id: UUID, limit: int) -> list[Row]:
    if limit <= 0:
        return []
    rows = await _all(
        conn,
        """
        SELECT role, content FROM messages
        WHERE conversation_id = %s
        ORDER BY created_at DESC, id DESC
        LIMIT %s
        """,
        (conv_id, limit),
    )
    return list(reversed(rows))


async def insert_message(
    conn: AsyncConnection,
    *,
    message_id: UUID,
    org_id: UUID,
    conv_id: UUID,
    role: str,
    content: str,
    status: str | None = None,
    metadata: dict | None = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO messages (id, organization_id, conversation_id, role, content, status, metadata)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (message_id, org_id, conv_id, role, content, status, json.dumps(metadata or {})),
    )


async def insert_citations(
    conn: AsyncConnection, org_id: UUID, message_id: UUID, citations: list[Row]
) -> None:
    if not citations:
        return
    async with conn.cursor() as cur:
        await cur.executemany(
            """
            INSERT INTO message_citations (organization_id, message_id, position, document_id,
                document_version_id, chunk_id, page_start, page_end, section)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    org_id,
                    message_id,
                    c["position"],
                    c["document_id"],
                    c["version_id"],
                    c["chunk_id"],
                    c["page_start"],
                    c["page_end"],
                    c["section"],
                )
                for c in citations
            ],
        )


async def insert_usage(
    conn: AsyncConnection,
    *,
    org_id: UUID,
    user_id: UUID,
    message_id: UUID | None,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    estimated_cost: Decimal | None,
) -> None:
    await conn.execute(
        """
        INSERT INTO usage_events (organization_id, user_id, message_id, kind, model,
            prompt_tokens, completion_tokens, estimated_cost)
        VALUES (%s, %s, %s, 'chat', %s, %s, %s, %s)
        """,
        (org_id, user_id, message_id, model, prompt_tokens, completion_tokens, estimated_cost),
    )


async def conversation_messages(conn: AsyncConnection, conv_id: UUID) -> list[Row]:
    return await _all(
        conn,
        """
        SELECT id, role, content, status, created_at, metadata FROM messages
        WHERE conversation_id = %s ORDER BY created_at, id
        """,
        (conv_id,),
    )


async def citations_for(conn: AsyncConnection, message_ids: list[UUID]) -> list[Row]:
    """Citations whose documents the caller can still read (RLS)."""
    if not message_ids:
        return []
    return await _all(
        conn,
        """
        SELECT mc.message_id, mc.position, mc.chunk_id, mc.document_id,
               mc.document_version_id AS version_id, mc.page_start, mc.page_end, mc.section,
               d.title AS document_title, v.version, v.effective_date
        FROM message_citations mc
        JOIN document_versions v ON v.id = mc.document_version_id
        JOIN documents d ON d.id = mc.document_id
        WHERE mc.message_id = ANY(%s)
        ORDER BY mc.message_id, mc.position
        """,
        (message_ids,),
    )
