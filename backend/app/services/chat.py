"""Chat orchestration around the LangGraph agent.

prepare() does the checks that must fail as normal HTTP errors (conversation
ownership, document scope). run() persists the question, runs the agent with
a server-built, immutable AuthContext, streams progress, then streams the
*verified* answer and persists it with citations, conflicts and usage.
"""

import asyncio
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.agents.graph import run_agent
from app.agents.nodes import ContextViolation
from app.agents.state import AgentDeps, AuthContext
from app.agents.tools.evidence import PostgresEvidenceSource
from app.agents.tools.reasoner import HeuristicReasoner, LLMReasoner
from app.auth.dependencies import OrgContext
from app.config import Settings
from app.db.session import UserDB
from app.repositories import chat as repo
from app.retrieval.authorize import SearchScope, allowed_documents
from app.retrieval.hybrid import HybridRetriever
from app.services import limits
from app.services.answering import Evidence, parse_citations
from app.services.llm import ChatLLM, Usage

logger = logging.getLogger(__name__)


class ConversationNotFound(Exception):
    pass


@dataclass
class ChatEvent:
    kind: str  # meta | step | delta | citations | done | error
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
    settings: Settings,
) -> PreparedChat:
    async with db.transaction() as conn:
        await limits.rate_limit(
            conn, ctx.org_id, "chat", settings.rate_limit_chat, settings.rate_limit_window_seconds
        )
        await limits.check_question(conn, settings, ctx.org_id)
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


def citation_dict(position: int, ev: Evidence) -> dict[str, Any]:
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


def _total_usage(model: str, usages: list[Usage]) -> Usage | None:
    if not usages:
        return None
    return Usage(
        model=model,
        prompt_tokens=sum(u.prompt_tokens for u in usages),
        completion_tokens=sum(u.completion_tokens for u in usages),
    )


def _cost(settings: Settings, usage: Usage | None) -> Decimal | None:
    if usage is None or settings.llm_input_price_per_1m is None:
        return None
    cost = (
        usage.prompt_tokens * settings.llm_input_price_per_1m
        + usage.completion_tokens * (settings.llm_output_price_per_1m or 0.0)
    ) / 1_000_000
    return Decimal(str(round(cost, 6)))


def build_reasoner(settings: Settings, llm: ChatLLM):
    if settings.llm_provider == "openai":
        return LLMReasoner(llm, settings.agent_sufficient_coverage)
    return HeuristicReasoner(settings.agent_sufficient_coverage)


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
        # Earlier answers are reused as context only if their sources are
        # still readable (revocation revalidation of "cached evidence").
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

    # Built by the server from the verified request; frozen; never in agent state.
    auth = AuthContext(organization_id=org, user_id=user_id, role=ctx.role, scope=prepared.scope)
    queue: asyncio.Queue[ChatEvent] = asyncio.Queue()

    async def emit(kind: str, data: dict) -> None:
        await queue.put(ChatEvent(kind, data))

    reasoner = build_reasoner(settings, llm)
    deps = AgentDeps(
        auth=auth,
        evidence=PostgresEvidenceSource(db, auth),
        retriever=retriever,
        llm=llm,
        reasoner=reasoner,
        settings=settings,
        emit=emit,
        deadline=time.monotonic() + settings.agent_timeout_seconds,
    )
    task = asyncio.create_task(run_agent(prepared.question, history, deps))
    while True:
        getter = asyncio.create_task(queue.get())
        done, _ = await asyncio.wait({task, getter}, return_when=asyncio.FIRST_COMPLETED)
        if getter in done:
            yield getter.result()
        else:
            getter.cancel()
        if task in done:
            break
    while not queue.empty():
        yield queue.get_nowait()

    trace_id = uuid.uuid4().hex
    try:
        state, trace_id = task.result()
    except ContextViolation:
        logger.error("agent context violation trace_id=%s", trace_id)
        state = {"status": "error", "answer": "The answer could not be generated."}
    except Exception as exc:
        logger.warning("agent failed: %s trace_id=%s", type(exc).__name__, trace_id)
        state = {
            "status": "error",
            "answer": "The answer could not be generated. Please try again.",
        }

    answer = state.get("answer") or ""
    status = state.get("status") or "error"
    answer_evidence = state.get("answer_evidence") or []
    cited = parse_citations(answer, len(answer_evidence)) if status == "answered" else []
    citations = [citation_dict(n, answer_evidence[n - 1]) for n in cited]
    usage = _total_usage(llm.name, [*state.get("usage", []), *getattr(reasoner, "usage", [])])
    latency_ms = int((time.perf_counter() - started) * 1000)
    details = {
        "trace_id": trace_id,
        "evidence_status": state.get("evidence_status", "none"),
        "conflicts": state.get("conflicts", [])
        if isinstance(state.get("conflicts"), list)
        and all(isinstance(c, dict) for c in state.get("conflicts", []))
        else [],
        "retrieval_attempts": state.get("attempts", 0),
        "steps": state.get("steps", 0),
    }
    stats = {
        "candidates": len(state.get("candidates") or []),
        "authorized": state.get("authorized_count", 0),
        "used": len(answer_evidence),
    }

    # Only verified text is streamed to the client.
    for piece in re.findall(r"\S+\s*", answer):
        yield ChatEvent("delta", {"text": piece})

    async with db.transaction() as conn:
        await repo.insert_message(
            conn,
            message_id=prepared.message_id,
            org_id=org,
            conv_id=prepared.conversation_id,
            role="assistant",
            content=answer,
            status=status,
            metadata={
                **details,
                "retrieval": stats,
                "latency_ms": latency_ms,
                "model": llm.name,
                "trace": state.get("trace", []),
                "verification": state.get("verification"),
                # Every document the answer was generated from: if any becomes
                # unreadable, the stored answer is hidden (revocation).
                "source_document_ids": sorted({str(e.document_id) for e in answer_evidence}),
            },
        )
        await repo.insert_citations(conn, org, prepared.message_id, citations)
        # One usage event per question, even when no model was called
        # (greetings, abstentions): the daily question quota counts these.
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

    logger.info(
        "chat answered trace_id=%s status=%s attempts=%s steps=%s",
        trace_id,
        status,
        details["retrieval_attempts"],
        details["steps"],
    )
    yield ChatEvent("citations", {"citations": citations})
    yield ChatEvent(
        "done",
        {
            "status": status,
            **details,
            "retrieval": stats,
            "usage": usage.__dict__ if usage else None,
            "latency_ms": latency_ms,
        },
    )
