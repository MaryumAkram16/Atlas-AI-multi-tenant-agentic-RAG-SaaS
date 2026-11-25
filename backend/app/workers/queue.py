"""Postgres-backed job queue (ADR 0002): claim with SKIP LOCKED, bounded
exponential backoff with jitter, attempts limit."""

import random
import re
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import psycopg


@dataclass(frozen=True)
class Job:
    id: UUID
    organization_id: UUID
    document_id: UUID | None
    document_version_id: UUID | None
    kind: str
    attempts: int
    max_attempts: int
    created_by: UUID
    run_after: datetime


def backoff_seconds(attempt: int, *, base: float, cap: float) -> float:
    """Delay before retry number `attempt` (1-based): half fixed, half jitter,
    within [ceiling/2, ceiling] where ceiling = min(cap, base * 2**(attempt-1))."""
    if base <= 0:
        return 0.0
    ceiling = min(cap, base * 2 ** min(attempt - 1, 30))
    return ceiling / 2 + random.uniform(0, ceiling / 2)  # noqa: S311 - not crypto


_SECRETISH = re.compile(r"(sk|pk|key|token|secret|bearer)[-_ ]?[A-Za-z0-9._-]{4,}", re.IGNORECASE)


def sanitize_error(exc: BaseException) -> str:
    """Error text safe to store and show: type plus a redacted, bounded message.
    Never includes document content (parsers raise their own messages)."""
    message = _SECRETISH.sub("[redacted]", str(exc))[:300]
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__


def claim(conn: psycopg.Connection, worker_id: str, lease_seconds: int) -> Job | None:
    row = conn.execute(
        "SELECT id, organization_id, document_id, document_version_id, kind, attempts,"
        " max_attempts, created_by, run_after"
        " FROM app_private.claim_ingestion_job(%s, %s)",
        (worker_id, lease_seconds),
    ).fetchone()
    return Job(**row) if row else None
