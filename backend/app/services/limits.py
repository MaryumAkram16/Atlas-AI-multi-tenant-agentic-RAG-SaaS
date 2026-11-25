"""Per-tenant quotas and per-user rate limits, both enforced in Postgres so
they hold across API instances."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from app.api.errors import ApiError
from app.config import Settings


@dataclass(frozen=True)
class Quota:
    documents: int | None
    storage_bytes: int | None
    questions_per_day: int | None


def plan_quota(settings: Settings, plan: str) -> Quota:
    if plan == "free":
        return Quota(
            settings.quota_free_documents,
            settings.quota_free_storage_mb * 1024 * 1024,
            settings.quota_free_questions_per_day,
        )
    if plan == "pro":
        return Quota(
            settings.quota_pro_documents,
            settings.quota_pro_storage_mb * 1024 * 1024,
            settings.quota_pro_questions_per_day,
        )
    return Quota(None, None, None)  # enterprise


async def org_plan(conn: AsyncConnection, org_id: UUID) -> str:
    cur = conn.cursor(row_factory=dict_row)
    await cur.execute("SELECT plan FROM organizations WHERE id = %s", (org_id,))
    row = await cur.fetchone()
    return row["plan"] if row else "free"


async def org_usage(conn: AsyncConnection, org_id: UUID, since: datetime) -> dict:
    cur = conn.cursor(row_factory=dict_row)
    await cur.execute("SELECT * FROM app_private.org_usage(%s, %s)", (org_id, since))
    row = await cur.fetchone()
    return (
        dict(row)
        if row
        else {
            "documents": 0,
            "storage_bytes": 0,
            "questions": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "estimated_cost": None,
        }
    )


async def rate_limit(
    conn: AsyncConnection, org_id: UUID, scope: str, limit: int, window_seconds: int
) -> None:
    cur = conn.cursor(row_factory=dict_row)
    await cur.execute(
        "SELECT * FROM app_private.consume_rate_limit(%s, %s, %s, %s)",
        (scope, org_id, limit, window_seconds),
    )
    row = await cur.fetchone()
    if not row["allowed"]:
        retry = max(1, int((row["reset_at"] - datetime.now(UTC)).total_seconds()) + 1)
        raise ApiError(
            429,
            "rate_limited",
            f"Too many {scope} requests. Try again in {retry} seconds.",
            headers={"Retry-After": str(retry)},
            limit=limit,
            window_seconds=window_seconds,
        )


def _exceeded(what: str, limit: int, used: int) -> ApiError:
    return ApiError(
        429,
        "quota_exceeded",
        f"Your plan's {what} limit has been reached.",
        quota=what,
        limit=limit,
        used=used,
    )


async def check_upload(
    conn: AsyncConnection, settings: Settings, org_id: UUID, *, new_document: bool, size_bytes: int
) -> None:
    quota = plan_quota(settings, await org_plan(conn, org_id))
    usage = await org_usage(conn, org_id, datetime.now(UTC))
    if new_document and quota.documents is not None and usage["documents"] >= quota.documents:
        raise _exceeded("documents", quota.documents, usage["documents"])
    if (
        quota.storage_bytes is not None
        and usage["storage_bytes"] + size_bytes > quota.storage_bytes
    ):
        raise _exceeded("storage", quota.storage_bytes, usage["storage_bytes"])


async def check_question(
    conn: AsyncConnection, settings: Settings, org_id: UUID, count: int = 1
) -> None:
    """Fail unless `count` more questions fit in today's quota."""
    quota = plan_quota(settings, await org_plan(conn, org_id))
    if quota.questions_per_day is None:
        return
    usage = await org_usage(conn, org_id, datetime.now(UTC) - timedelta(days=1))
    if usage["questions"] + count > quota.questions_per_day:
        raise _exceeded("questions per day", quota.questions_per_day, usage["questions"])
