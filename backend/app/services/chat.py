"""Baseline RAG pipeline for one question:

validate scope (Postgres) -> hybrid search (Qdrant, filtered) -> recheck
chunk IDs and load text (Postgres, RLS) -> top chunks -> grounded answer with
citations -> persist message, citations and usage.

Tenant identity comes only from the verified request context, never from the
model or from document content.
"""

import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi.concurrency import run_in_threadpool

from app.auth.dependencies import OrgContext
from app.config import Settings
from app.db.session import UserDB
from app.repositories import chat as repo
from app.retrieval.authorize import SearchScope, allowed_documents, load_authorized_chunks
from app.retrieval.hybrid import HybridRetriever
from app.services.answering import (
    INSUFFICIENT_EVIDENCE_ANSWER,
    Evidence,
    build_messages,
    is_insufficient,
    parse_citations,
)
from app.services.llm import ChatLLM, TextDelta, Usage

logger = logging.getLogger(__name__)


class ConversationNotFound(Exception):
    pass


@dataclass
class ChatEvent:
    kind: str  # meta | delta | citations | done | error
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PreparedChat:
    question: str
    conversation_id: UUID
    is_new_conversation: bool
    message_id: UUID
    scope: SearchScope


async def prepare(
    db: UserDB,
    ctx: OrgContext,
    question: str,
    conversation_id: UUID | None,
    document_ids: list[UUID] | None,
) -> PreparedChat:
    """Validation that must fail with a normal HTTP error, before streaming."""
    async with db.transaction() as conn:
        if conversation_id is not None:
            if await repo.get_conversation(conn, ctx.org_id, conversation_id) is None:
                raise ConversationNotFound()
        scope = await allowed_documents(conn, ctx.org_id, document_ids)
    return PreparedChat(
        question=question,
        conversation_id=conversation_id or uuid.uuid4(),
        is_new_conversation=conversation_id is None,
        message_id=uuid.uuid4(),
        scope=scope,
    )


def _citation(position: int, ev: Evidence) -> dict[str, Any]:
    return {
        "position": position,
        "chunk_id": ev.chunk_id,
        "document_id": ev.document_id,
        "document_title": ev.document_title,
        "version_id": ev.version_id,
        "version": ev.version,
        "effective_date": ev.effective_date,
        "section": ev.section,
        "page_start": ev.page_start,
        "page_end": ev.page_end,
    }


def _cost(settings: Settings, usage: Usage | None) -> Decimal | None:
    if usage is None or settings.llm_input_price_per_1m is None:
        return None
    out_price = settings.llm_output_price_per_1m or 0.0
    cost = (
        usage.prompt_tokens * settings.llm_input_price_per_1m + usage.completion_tokens * out_price
    ) / 1_000_000
    return Decimal(str(round(cost, 6)))


async def run(
    *,
    prepared: PreparedChat,
    ctx: OrgContext,
    db: UserDB,
    retriever: HybridRetriever,
    llm: ChatLLM,
    settings: Settings,
) -> AsyncIterator[ChatEvent]:
    started = time.perf_counter()
    org, user_id = ctx.org_id, ctx.user.user_id
    yield ChatEvent(
        "meta",
        {"conversation_id": str(prepared.conversation_id), "message_id": str(prepared.message_id)},
    )

    async with db.transaction() as conn:
        if prepared.is_new_conversation:
            await repo.create_conversation(
                conn, prepared.conversation_id, org, user_id, prepared.question[:200]
            )
        history = await repo.recent_messages(
            conn, prepared.conversation_id, settings.chat_history_messages
        )
        await repo.insert_message(
            conn,
            message_id=uuid.uuid4(),
            org_id=org,
            conv_id=prepared.conversation_id,
            role="user",
            content=prepared.question,
        )

    candidates = await run_in_threadpool(
        retriever.retrieve,
        prepared.question,
        organization_id=org,
        document_ids=prepared.scope.document_ids,
        version_ids=prepared.scope.version_ids,
    )
    async with db.transaction() as conn:
        authorized = await load_authorized_chunks(
            conn,
            org,
            [c.chunk_id for c in candidates],
            prepared.scope.document_ids,
            scores={c.chunk_id: c.score for c in candidates},
        )
    evidence = authorized[: settings.answer_max_chunks]
    stats = {"candidates": len(candidates), "authorized": len(authorized), "used": len(evidence)}

    usage: Usage | None = None
    status = "answered"
    if not evidence:
        answer, status = INSUFFICIENT_EVIDENCE_ANSWER, "insufficient_evidence"
        yield ChatEvent("delta", {"text": answer})
    else:
        parts: list[str] = []
        try:
            messages = build_messages(prepared.question, evidence, history)
            async for event in llm.stream(messages):
                if isinstance(event, TextDelta):
                    parts.append(event.text)
                    yield ChatEvent("delta", {"text": event.text})
                elif isinstance(event, Usage):
                    usage = event
            answer = "".join(parts).strip()
            if is_insufficient(answer):
                status = "insufficient_evidence"
        except Exception as exc:
            logger.warning("generation failed: %s", type(exc).__name__)
            answer, status = "The answer could not be generated. Please try again.", "error"
            yield ChatEvent("error", {"message": answer})

    cited = parse_citations(answer, len(evidence)) if status == "answered" else []
    citations = [_citation(n, evidence[n - 1]) for n in cited]
    latency_ms = int((time.perf_counter() - started) * 1000)

    async with db.transaction() as conn:
        await repo.insert_message(
            conn,
            message_id=prepared.message_id,
            org_id=org,
            conv_id=prepared.conversation_id,
            role="assistant",
            content=answer,
            status=status,
            metadata={"retrieval": stats, "latency_ms": latency_ms, "model": llm.name},
        )
        await repo.insert_citations(conn, org, prepared.message_id, citations)
        if usage is not None or evidence:
            await repo.insert_usage(
                conn,
                org_id=org,
                user_id=user_id,
                message_id=prepared.message_id,
                model=usage.model if usage else llm.name,
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
                estimated_cost=_cost(settings, usage),
            )
        await repo.touch_conversation(conn, prepared.conversation_id)

    yield ChatEvent("citations", {"citations": citations})
    yield ChatEvent(
        "done",
        {
            "status": status,
            "retrieval": stats,
            "usage": usage.__dict__ if usage else None,
            "latency_ms": latency_ms,
        },
    )
