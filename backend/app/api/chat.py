"""Chat and conversation endpoints. POST /chat streams Server-Sent Events
when the client sends `Accept: text/event-stream`, otherwise returns JSON."""

import json
from collections import defaultdict
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse

from app.auth.dependencies import DB, Org
from app.repositories import chat as repo
from app.retrieval.authorize import DocumentNotAllowed
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    Citation,
    ConversationDetail,
    ConversationOut,
    MessageOut,
)
from app.services import chat as service

router = APIRouter(prefix="/v1/organizations/{org_id}", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest, request: Request, ctx: Org, db: DB):
    try:
        prepared = await service.prepare(
            db, ctx, body.question, body.conversation_id, body.document_ids
        )
    except service.ConversationNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="conversation not found") from None
    except DocumentNotAllowed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="document not found") from None

    state = request.app.state
    events = service.run(
        prepared=prepared,
        ctx=ctx,
        db=db,
        retriever=state.retriever,
        llm=state.llm,
        settings=state.settings,
    )

    if "text/event-stream" in request.headers.get("accept", ""):

        async def sse():
            async for event in events:
                payload = json.dumps(jsonable_encoder(event.data))
                yield f"event: {event.kind}\ndata: {payload}\n\n"

        return StreamingResponse(
            sse(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    answer, meta, citations, done = [], {}, [], {}
    async for event in events:
        if event.kind == "meta":
            meta = event.data
        elif event.kind == "delta":
            answer.append(event.data["text"])
        elif event.kind == "citations":
            citations = event.data["citations"]
        elif event.kind == "done":
            done = event.data
    return ChatResponse(
        conversation_id=meta["conversation_id"],
        message_id=meta["message_id"],
        answer="".join(answer).strip(),
        status=done["status"],
        citations=citations,
        retrieval=done["retrieval"],
        usage=done["usage"],
        latency_ms=done["latency_ms"],
    )


@router.get("/conversations")
async def list_conversations(ctx: Org, db: DB) -> list[ConversationOut]:
    async with db.transaction() as conn:
        rows = await repo.list_conversations(conn, ctx.org_id, ctx.user.user_id)
    return [ConversationOut(**r) for r in rows]


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: UUID, ctx: Org, db: DB) -> ConversationDetail:
    async with db.transaction() as conn:
        conv = await repo.get_conversation(conn, ctx.org_id, conversation_id)
        if conv is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="conversation not found")
        messages = await repo.conversation_messages(conn, conversation_id)
        citations = await repo.citations_for(conn, [m["id"] for m in messages])
    by_message: dict[UUID, list[Citation]] = defaultdict(list)
    for c in citations:
        by_message[c.pop("message_id")].append(Citation(**c))
    return ConversationDetail(
        **conv,
        messages=[MessageOut(**m, citations=by_message.get(m["id"], [])) for m in messages],
    )
