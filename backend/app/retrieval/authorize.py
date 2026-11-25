"""Postgres is the authority (CLAUDE.md). Two checks bracket every search:

1. allowed_documents(): which published documents the caller may search,
   computed under RLS before Qdrant is queried (the Qdrant filter uses it).
2. load_authorized_chunks(): every candidate chunk ID returned by Qdrant is
   rechecked under RLS (document_access) and must belong to an allowed,
   ready document's *current* version. Text is loaded only here, only for
   chunks that pass, so nothing unauthorized can reach a reranker or LLM.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from app.services.answering import Evidence


class DocumentNotAllowed(Exception):
    """A requested document does not exist or is not readable by the caller."""


@dataclass(frozen=True)
class SearchScope:
    document_ids: list[UUID]
    version_ids: list[UUID]


async def allowed_documents(
    conn: AsyncConnection, org_id: UUID, requested: Sequence[UUID] | None
) -> SearchScope:
    cur = conn.cursor(row_factory=dict_row)
    await cur.execute(
        """
        SELECT d.id, d.current_version_id
        FROM documents d
        WHERE d.organization_id = %s AND d.status = 'ready' AND d.current_version_id IS NOT NULL
        """,
        (org_id,),
    )
    rows = await cur.fetchall()
    readable = {r["id"]: r["current_version_id"] for r in rows}
    if requested is not None:
        missing = set(requested) - readable.keys()
        if missing:
            raise DocumentNotAllowed()
        readable = {d: v for d, v in readable.items() if d in set(requested)}
    return SearchScope(document_ids=list(readable), version_ids=list(readable.values()))


async def load_authorized_chunks(
    conn: AsyncConnection,
    org_id: UUID,
    candidate_ids: Sequence[UUID],
    allowed_document_ids: Sequence[UUID],
    scores: dict[UUID, float] | None = None,
) -> list[Evidence]:
    if not candidate_ids or not allowed_document_ids:
        return []
    cur = conn.cursor(row_factory=dict_row)
    await cur.execute(
        """
        SELECT c.id, c.document_id, c.document_version_id, c.content, c.section,
               c.page_start, c.page_end, d.title, v.version, v.effective_date
        FROM document_chunks c
        JOIN document_versions v ON v.id = c.document_version_id
        JOIN documents d ON d.id = c.document_id
        WHERE c.id = ANY(%s)
          AND c.organization_id = %s
          AND c.document_id = ANY(%s)
          AND c.embedding_status = 'indexed'
          AND v.status = 'published'
          AND d.status = 'ready'
          AND d.current_version_id = v.id
        """,
        (list(candidate_ids), org_id, list(allowed_document_ids)),
    )
    rows = {r["id"]: r for r in await cur.fetchall()}
    scores = scores or {}
    return [
        Evidence(
            chunk_id=cid,
            document_id=rows[cid]["document_id"],
            document_title=rows[cid]["title"],
            version_id=rows[cid]["document_version_id"],
            version=rows[cid]["version"],
            effective_date=rows[cid]["effective_date"],
            section=rows[cid]["section"],
            page_start=rows[cid]["page_start"],
            page_end=rows[cid]["page_end"],
            content=rows[cid]["content"],
            score=scores.get(cid, 0.0),
        )
        for cid in candidate_ids
        if cid in rows
    ]
