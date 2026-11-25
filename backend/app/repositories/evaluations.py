"""Evaluation data access (inside UserDB transactions; RLS applies)."""

import json
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import dict_row

Row = dict[str, Any]

_DATASET = """
    SELECT d.id, d.name, d.description, d.created_by, d.created_at, d.updated_at,
           (SELECT count(*) FROM evaluation_cases c WHERE c.dataset_id = d.id) AS case_count
    FROM evaluation_datasets d
"""
_CASE = """
    SELECT id, dataset_id, question, expected_facts, expected_document_ids, should_abstain,
           created_at
    FROM evaluation_cases
"""
_RUN = """
    SELECT id, dataset_id, dataset_name, status, config, metrics, case_count, error,
           created_by, created_at, finished_at
    FROM evaluation_runs
"""


async def _all(conn: AsyncConnection, query: str, params: tuple) -> list[Row]:
    cur = conn.cursor(row_factory=dict_row)
    await cur.execute(query, params)
    return await cur.fetchall()


async def _one(conn: AsyncConnection, query: str, params: tuple) -> Row | None:
    rows = await _all(conn, query, params)
    return rows[0] if rows else None


# ---------- datasets ----------


async def insert_dataset(
    conn: AsyncConnection,
    *,
    dataset_id: UUID,
    org_id: UUID,
    name: str,
    description: str | None,
    created_by: UUID,
) -> None:
    await conn.execute(
        """
        INSERT INTO evaluation_datasets (id, organization_id, name, description, created_by)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (dataset_id, org_id, name, description, created_by),
    )


async def list_datasets(conn: AsyncConnection, org_id: UUID) -> list[Row]:
    return await _all(
        conn, _DATASET + " WHERE d.organization_id = %s ORDER BY d.created_at DESC", (org_id,)
    )


async def get_dataset(conn: AsyncConnection, org_id: UUID, dataset_id: UUID) -> Row | None:
    return await _one(
        conn, _DATASET + " WHERE d.organization_id = %s AND d.id = %s", (org_id, dataset_id)
    )


async def delete_dataset(conn: AsyncConnection, org_id: UUID, dataset_id: UUID) -> bool:
    cur = await conn.execute(
        "DELETE FROM evaluation_datasets WHERE organization_id = %s AND id = %s",
        (org_id, dataset_id),
    )
    return cur.rowcount > 0


# ---------- cases ----------


async def insert_cases(
    conn: AsyncConnection, org_id: UUID, dataset_id: UUID, cases: list[dict]
) -> None:
    async with conn.cursor() as cur:
        await cur.executemany(
            """
            INSERT INTO evaluation_cases (organization_id, dataset_id, question,
                expected_facts, expected_document_ids, should_abstain)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    org_id,
                    dataset_id,
                    c["question"],
                    c["expected_facts"],
                    c["expected_document_ids"],
                    c["should_abstain"],
                )
                for c in cases
            ],
        )


async def list_cases(conn: AsyncConnection, org_id: UUID, dataset_id: UUID) -> list[Row]:
    return await _all(
        conn,
        _CASE + " WHERE organization_id = %s AND dataset_id = %s ORDER BY seq",
        (org_id, dataset_id),
    )


async def delete_case(conn: AsyncConnection, org_id: UUID, dataset_id: UUID, case_id: UUID) -> bool:
    cur = await conn.execute(
        "DELETE FROM evaluation_cases WHERE organization_id = %s AND dataset_id = %s AND id = %s",
        (org_id, dataset_id, case_id),
    )
    return cur.rowcount > 0


async def readable_document_ids(conn: AsyncConnection, org_id: UUID, ids: list[UUID]) -> set[UUID]:
    rows = await _all(
        conn,
        "SELECT id FROM documents WHERE organization_id = %s AND id = ANY(%s)",
        (org_id, ids),
    )
    return {r["id"] for r in rows}


# ---------- runs ----------


async def insert_run(
    conn: AsyncConnection,
    *,
    run_id: UUID,
    org_id: UUID,
    dataset: Row,
    config: dict,
    case_count: int,
    created_by: UUID,
) -> None:
    await conn.execute(
        """
        INSERT INTO evaluation_runs (id, organization_id, dataset_id, dataset_name, config,
            case_count, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            run_id,
            org_id,
            dataset["id"],
            dataset["name"],
            json.dumps(config),
            case_count,
            created_by,
        ),
    )


async def finish_run(
    conn: AsyncConnection, run_id: UUID, *, status: str, metrics: dict | None, error: str | None
) -> None:
    await conn.execute(
        """
        UPDATE evaluation_runs SET status = %s, metrics = %s, error = %s, finished_at = now()
        WHERE id = %s
        """,
        (status, json.dumps(metrics) if metrics is not None else None, error, run_id),
    )


async def list_runs(conn: AsyncConnection, org_id: UUID, limit: int) -> list[Row]:
    return await _all(
        conn,
        _RUN + " WHERE organization_id = %s ORDER BY created_at DESC, id LIMIT %s",
        (org_id, limit),
    )


async def get_run(conn: AsyncConnection, org_id: UUID, run_id: UUID) -> Row | None:
    return await _one(conn, _RUN + " WHERE organization_id = %s AND id = %s", (org_id, run_id))


# ---------- results ----------


async def insert_result(conn: AsyncConnection, org_id: UUID, run_id: UUID, r: dict) -> None:
    await conn.execute(
        """
        INSERT INTO evaluation_results (organization_id, run_id, case_id, position, question,
            status, answer, abstained, fact_hit, abstention_correct, evidence_hit,
            cited_document_ids, source_document_ids, latency_ms, prompt_tokens,
            completion_tokens)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            org_id,
            run_id,
            r["case_id"],
            r["position"],
            r["question"],
            r["status"],
            r["answer"],
            r["abstained"],
            r["fact_hit"],
            r["abstention_correct"],
            r["evidence_hit"],
            r["cited_document_ids"],
            r["source_document_ids"],
            r["latency_ms"],
            r["prompt_tokens"],
            r["completion_tokens"],
        ),
    )


async def list_results(conn: AsyncConnection, org_id: UUID, run_id: UUID) -> list[Row]:
    """RLS returns only results whose sources the caller can read (or their own run)."""
    return await _all(
        conn,
        """
        SELECT case_id, position, question, status, answer, abstained, fact_hit,
               abstention_correct, evidence_hit, cited_document_ids, latency_ms,
               prompt_tokens, completion_tokens
        FROM evaluation_results
        WHERE organization_id = %s AND run_id = %s
        ORDER BY position
        """,
        (org_id, run_id),
    )
