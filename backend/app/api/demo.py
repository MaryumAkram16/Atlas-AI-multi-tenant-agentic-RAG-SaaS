"""Public demo: an anonymous visitor joins the operator-chosen sample workspace.

POST /v1/demo/join (anonymous Supabase session) -> {"organization_id": ...}
The database decides which organization (app_private.demo_config) and grants
only the viewer role; this endpoint never takes an organization from the client.
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.auth.dependencies import DB, CurrentUser

router = APIRouter(prefix="/v1/demo", tags=["demo"])


class DemoJoined(BaseModel):
    organization_id: UUID


@router.post("/join")
async def join_demo(user: CurrentUser, db: DB) -> DemoJoined:
    if not user.is_anonymous:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="the demo workspace is for anonymous visitors"
        )
    async with db.transaction() as conn:
        cur = await conn.execute("SELECT app_private.join_demo() AS org")
        row = await cur.fetchone()
    if row is None or row["org"] is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="no demo workspace is configured")
    return DemoJoined(organization_id=row["org"])
