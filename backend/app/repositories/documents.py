"""Document data access, always inside a UserDB transaction (RLS applies)."""

import json
from datetime import date
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection

from app.observability.tracing import inject_context

Row = dict[str, Any]


async def _one(conn: AsyncConnection, query: str, params: tuple) -> Row | None:
    cur = await conn.execute(query, params)
    return await cur.fetchone()


async def _all(conn: AsyncConnection, query: str, params: tuple) -> list[Row]:
    cur = await conn.execute(query, params)
    return await cur.fetchall()


async def document_access(conn: AsyncConnection, document_id: UUID) -> str | None:
    row = await _one(conn, "SELECT app_private.document_access(%s) AS access", (document_id,))
    return row["access"]


# ---------- documents ----------


async def get_document(conn: AsyncConnection, org_id: UUID, document_id: UUID) -> Row | None:
    return await _one(
        conn,
        """
        SELECT id, organization_id, owner_id, title, visibility, status, created_at,
               updated_at, current_version_id
        FROM documents
        WHERE organization_id = %s AND id = %s
        """,
        (org_id, document_id),
    )


async def list_documents(conn: AsyncConnection, org_id: UUID) -> list[Row]:
    return await _all(
        conn,
        """
        SELECT id, organization_id, owner_id, title, visibility, status, created_at,
               updated_at, current_version_id
        FROM documents
        WHERE organization_id = %s
        ORDER BY created_at DESC, id
        """,
        (org_id,),
    )


async def insert_document(
    conn: AsyncConnection,
    *,
    document_id: UUID,
    org_id: UUID,
    owner_id: UUID,
    title: str,
    visibility: str,
) -> None:
    await conn.execute(
        """
        INSERT INTO documents (id, organization_id, owner_id, title, visibility)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (document_id, org_id, owner_id, title, visibility),
    )


async def mark_deleting(conn: AsyncConnection, document_id: UUID) -> bool:
    row = await _one(conn, "SELECT app_private.mark_document_deleting(%s) AS ok", (document_id,))
    return bool(row["ok"])


# ---------- versions ----------


async def versions_by_id(conn: AsyncConnection, version_ids: list[UUID]) -> dict[UUID, Row]:
    if not version_ids:
        return {}
    rows = await _all(
        conn,
        """
        SELECT id, document_id, version, filename, mime_type, size_bytes, checksum,
               effective_date, status, chunk_count, error, created_at, published_at,
               storage_path
        FROM document_versions
        WHERE id = ANY(%s)
        """,
        (version_ids,),
    )
    return {r["id"]: r for r in rows}


async def list_versions(conn: AsyncConnection, document_id: UUID) -> list[Row]:
    return await _all(
        conn,
        """
        SELECT id, document_id, version, filename, mime_type, size_bytes, checksum,
               effective_date, status, chunk_count, error, created_at, published_at,
               storage_path
        FROM document_versions
        WHERE document_id = %s
        ORDER BY version DESC
        """,
        (document_id,),
    )


async def get_version(
    conn: AsyncConnection, org_id: UUID, document_id: UUID, version_id: UUID
) -> Row | None:
    return await _one(
        conn,
        """
        SELECT id, document_id, version, filename, mime_type, size_bytes, checksum,
               effective_date, status, chunk_count, error, created_at, published_at,
               storage_path
        FROM document_versions
        WHERE organization_id = %s AND document_id = %s AND id = %s
        """,
        (org_id, document_id, version_id),
    )


async def find_duplicate(conn: AsyncConnection, org_id: UUID, checksum: str) -> UUID | None:
    """Only documents visible to the caller are considered, so a 409 never
    reveals the existence of a document they cannot read."""
    row = await _one(
        conn,
        """
        SELECT v.document_id FROM document_versions v
        JOIN documents d ON d.id = v.document_id
        WHERE v.organization_id = %s AND v.checksum = %s
          AND v.status <> 'failed' AND d.status <> 'deleting'
        LIMIT 1
        """,
        (org_id, checksum),
    )
    return row["document_id"] if row else None


async def next_version_number(conn: AsyncConnection, document_id: UUID) -> int:
    row = await _one(
        conn,
        "SELECT coalesce(max(version), 0) + 1 AS n FROM document_versions WHERE document_id = %s",
        (document_id,),
    )
    return row["n"]


async def insert_version(
    conn: AsyncConnection,
    *,
    version_id: UUID,
    org_id: UUID,
    document_id: UUID,
    version: int,
    filename: str,
    mime_type: str,
    size_bytes: int,
    checksum: str,
    storage_path: str,
    effective_date: date | None,
    created_by: UUID,
) -> None:
    await conn.execute(
        """
        INSERT INTO document_versions
            (id, organization_id, document_id, version, filename, mime_type, size_bytes,
             checksum, storage_path, effective_date, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            version_id,
            org_id,
            document_id,
            version,
            filename,
            mime_type,
            size_bytes,
            checksum,
            storage_path,
            effective_date,
            created_by,
        ),
    )


async def get_chunk(
    conn: AsyncConnection, org_id: UUID, document_id: UUID, chunk_id: UUID
) -> Row | None:
    """One chunk for a source preview. RLS (document_access) decides visibility."""
    return await _one(
        conn,
        """
        SELECT c.id AS chunk_id, c.document_id, d.title AS document_title,
               c.document_version_id AS version_id, v.version, v.effective_date,
               c.section, c.page_start, c.page_end, c.content
        FROM document_chunks c
        JOIN document_versions v ON v.id = c.document_version_id
        JOIN documents d ON d.id = c.document_id
        WHERE c.organization_id = %s AND c.document_id = %s AND c.id = %s
        """,
        (org_id, document_id, chunk_id),
    )


# ---------- jobs ----------


async def insert_job(
    conn: AsyncConnection,
    *,
    org_id: UUID,
    document_id: UUID,
    version_id: UUID | None,
    kind: str,
    idempotency_key: str,
    max_attempts: int,
    created_by: UUID,
) -> Row:
    return await _one(
        conn,
        """
        INSERT INTO ingestion_jobs
            (organization_id, document_id, document_version_id, kind, idempotency_key,
             max_attempts, created_by, trace_context)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id, organization_id, document_id, document_version_id, kind, status,
                  attempts, max_attempts, run_after, last_error, created_at, updated_at,
                  finished_at
        """,
        (
            org_id,
            document_id,
            version_id,
            kind,
            idempotency_key,
            max_attempts,
            created_by,
            # W3C trace context: the worker continues this request's trace.
            json.dumps(inject_context()),
        ),
    )


async def get_job(conn: AsyncConnection, org_id: UUID, job_id: UUID) -> Row | None:
    return await _one(
        conn,
        """
        SELECT id, organization_id, document_id, document_version_id, kind, status, attempts,
               max_attempts, run_after, last_error, created_at, updated_at, finished_at
        FROM ingestion_jobs
        WHERE organization_id = %s AND id = %s
        """,
        (org_id, job_id),
    )


async def job_by_key(conn: AsyncConnection, org_id: UUID, key: str) -> Row | None:
    return await _one(
        conn,
        """
        SELECT id, organization_id, document_id, document_version_id, kind, status, attempts,
               max_attempts, run_after, last_error, created_at, updated_at, finished_at
        FROM ingestion_jobs
        WHERE organization_id = %s AND idempotency_key = %s
        """,
        (org_id, key),
    )
