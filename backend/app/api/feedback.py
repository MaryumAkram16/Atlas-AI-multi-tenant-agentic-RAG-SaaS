"""Answer feedback: rate your own answers; owners/admins review it.

PUT/DELETE /v1/organizations/{org_id}/conversations/{cid}/messages/{mid}/feedback
GET /v1/organizations/{org_id}/feedback
"""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.auth.dependencies import DB, Org
from app.repositories import feedback as repo
from app.schemas.feedback import FeedbackIn, FeedbackOut, FeedbackReviewOut

router = APIRouter(prefix="/v1/organizations/{org_id}", tags=["feedback"])

_PATH = "/conversations/{conversation_id}/messages/{message_id}/feedback"


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, detail="message not found")


@router.put(_PATH)
async def give_feedback(
    conversation_id: UUID, message_id: UUID, body: FeedbackIn, ctx: Org, db: DB
) -> FeedbackOut:
    """Rate an answer in one of your own conversations. Your question, rating,
    reason and comment become visible to workspace owners and admins."""
    async with db.transaction() as conn:
        msg = await repo.assistant_message(conn, ctx.org_id, conversation_id, message_id)
        if msg is None or not msg["question"]:
            raise _not_found()
        row = await repo.upsert(
            conn,
            org_id=ctx.org_id,
            message_id=message_id,
            user_id=ctx.user.user_id,
            rating=body.rating,
            reason=body.reason,
            comment=body.comment,
            question=msg["question"][:4000],
            answer_status=msg["status"],
        )
    return FeedbackOut(**row)


@router.delete(_PATH, status_code=status.HTTP_204_NO_CONTENT)
async def remove_feedback(conversation_id: UUID, message_id: UUID, ctx: Org, db: DB) -> Response:
    async with db.transaction() as conn:
        if await repo.assistant_message(conn, ctx.org_id, conversation_id, message_id) is None:
            raise _not_found()
        if not await repo.delete(conn, ctx.org_id, message_id, ctx.user.user_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="no feedback to remove")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/feedback")
async def review_feedback(
    ctx: Org,
    db: DB,
    rating: Literal["up", "down"] | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[FeedbackReviewOut]:
    if not ctx.is_manager:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="only owners and admins can review feedback"
        )
    async with db.transaction() as conn:
        rows = await repo.review(conn, ctx.org_id, rating, limit)
    return [FeedbackReviewOut(**r) for r in rows]
