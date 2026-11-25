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
    """Immutable: what the caller may search. Built from Postgres, never from
    model output. history_version_ids adds superseded versions, used only for
    explicit version comparisons."""

    document_ids: tuple[UUID, ...]
    version_ids: tuple[UUID, ...]
    history_version_ids: tuple[UUID, ...] = ()


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
    history: tuple[UUID, ...] = ()
    if readable:
        await cur.execute(
            """
            SELECT v.id FROM document_versions v
            WHERE v.organization_id = %s AND v.document_id = ANY(%s)
              AND v.status IN ('published', 'superseded')
            """,
            (org_id, list(readable)),
        )
        history = tuple(r["id"] for r in await cur.fetchall())
    return SearchScope(
        document_ids=tuple(readable),
        version_ids=tuple(readable.values()),
        history_version_ids=history,
    )


_CHUNKS_CURRENT = """
    SELECT c.id, c.document_id, c.document_version_id, c.content, c.section,
           c.page_start, c.page_end, d.title, v.version, v.effective_date
    FROM document_chunks c
    JOIN document_versions v ON v.id = c.document_version_id
    JOIN documents d ON d.id = c.document_id
    WHERE c.id = ANY(%s)
      AND c.organization_id = %s
      AND c.document_id = ANY(%s)
      AND c.embedding_status = 'indexed'
      AND d.status = 'ready'
      AND v.status = 'published'
      AND d.current_version_id = v.id
"""
_CHUNKS_WITH_HISTORY = """
    SELECT c.id, c.document_id, c.document_version_id, c.content, c.section,
           c.page_start, c.page_end, d.title, v.version, v.effective_date
    FROM document_chunks c
    JOIN document_versions v ON v.id = c.document_version_id
    JOIN documents d ON d.id = c.document_id
    WHERE c.id = ANY(%s)
      AND c.organization_id = %s
      AND c.document_id = ANY(%s)
      AND c.embedding_status = 'indexed'
      AND d.status = 'ready'
      AND v.status IN ('published', 'superseded')
"""


async def load_authorized_chunks(
    conn: AsyncConnection,
    org_id: UUID,
    candidate_ids: Sequence[UUID],
    allowed_document_ids: Sequence[UUID],
    scores: dict[UUID, float] | None = None,
    include_history: bool = False,
) -> list[Evidence]:
    """include_history also admits superseded versions of allowed documents
    (explicit comparisons only); otherwise only the current published version."""
    if not candidate_ids or not allowed_document_ids:
        return []
    cur = conn.cursor(row_factory=dict_row)
    # Two fixed queries (no string-built SQL): current versions only, or
    # current plus superseded versions for explicit comparisons.
    query = _CHUNKS_WITH_HISTORY if include_history else _CHUNKS_CURRENT
    await cur.execute(query, (list(candidate_ids), org_id, list(allowed_document_ids)))
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


async def load_version_headers(
    conn: AsyncConnection, org_id: UUID, version_ids: Sequence[UUID]
) -> dict[UUID, str]:
    """First chunk of each version (title block: policy ID, supersedes,
    status), read under RLS, for version comparison."""
    if not version_ids:
        return {}
    cur = conn.cursor(row_factory=dict_row)
    await cur.execute(
        """
        SELECT document_version_id, content FROM document_chunks
        WHERE organization_id = %s AND document_version_id = ANY(%s) AND chunk_index = 0
        """,
        (org_id, list(version_ids)),
    )
    return {r["document_version_id"]: r["content"] for r in await cur.fetchall()}
