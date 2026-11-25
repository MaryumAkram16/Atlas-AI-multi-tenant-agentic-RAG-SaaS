"""Usage and audit history (/v1/organizations/{org_id}/usage, /audit-logs)."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query, Request
from psycopg.rows import dict_row

from app.api.errors import ApiError
from app.auth.dependencies import DB, Org
from app.schemas.admin import AuditLogOut, UsageOut, UsageTotals
from app.services import limits

router = APIRouter(prefix="/v1/organizations/{org_id}", tags=["admin"])


@router.get("/usage")
async def usage(
    ctx: Org, db: DB, request: Request, days: Annotated[int, Query(ge=1, le=90)] = 30
) -> UsageOut:
    """Your own usage; owners and admins also get organization totals and quotas."""
    since = datetime.now(UTC) - timedelta(days=days)
    settings = request.app.state.settings
    async with db.transaction() as conn:
        cur = conn.cursor(row_factory=dict_row)
        await cur.execute(
            """
            SELECT count(*) FILTER (WHERE kind = 'chat') AS questions,
                   coalesce(sum(prompt_tokens), 0) AS prompt_tokens,
                   coalesce(sum(completion_tokens), 0) AS completion_tokens,
                   sum(estimated_cost) AS estimated_cost
            FROM usage_events
            WHERE organization_id = %s AND user_id = %s AND created_at >= %s
            """,
            (ctx.org_id, ctx.user.user_id, since),
        )
        mine = await cur.fetchone()
        org_totals = quota = None
        if ctx.is_manager:
            org_totals = await limits.org_usage(conn, ctx.org_id, since)
            today = await limits.org_usage(conn, ctx.org_id, datetime.now(UTC) - timedelta(days=1))
            plan = await limits.org_plan(conn, ctx.org_id)
            q = limits.plan_quota(settings, plan)
            quota = {
                "plan": plan,
                "documents": {"limit": q.documents, "used": org_totals["documents"]},
                "storage_bytes": {"limit": q.storage_bytes, "used": org_totals["storage_bytes"]},
                "questions_per_day": {"limit": q.questions_per_day, "used": today["questions"]},
            }
    return UsageOut(
        period_days=days,
        me=UsageTotals(**mine),
        organization=UsageTotals(**{k: org_totals[k] for k in UsageTotals.model_fields})
        if org_totals
        else None,
        documents=org_totals["documents"] if org_totals else None,
        storage_bytes=org_totals["storage_bytes"] if org_totals else None,
        quota=quota,
    )


@router.get("/audit-logs")
async def audit_logs(
    ctx: Org,
    db: DB,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before_id: Annotated[int | None, Query(ge=1)] = None,
    action: Annotated[str | None, Query(max_length=64)] = None,
) -> list[AuditLogOut]:
    """Owners and admins; newest first. Page with `before_id`."""
    if not ctx.is_manager:
        raise ApiError(403, "forbidden", "Only owners and admins can view audit logs.")
    async with db.transaction() as conn:
        cur = conn.cursor(row_factory=dict_row)
        await cur.execute(
            """
            SELECT id, actor_id, actor_type, action, resource_type, resource_id, metadata,
                   created_at
            FROM audit_logs
            WHERE organization_id = %s
              AND (%s::bigint IS NULL OR id < %s)
              AND (%s::text IS NULL OR action = %s)
            ORDER BY id DESC
            LIMIT %s
            """,
            (ctx.org_id, before_id, before_id, action, action, limit),
        )
        rows = await cur.fetchall()
    return [AuditLogOut(**r) for r in rows]
