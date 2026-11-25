"""The Week 3 baseline pipeline (hybrid search -> recheck -> top chunks ->
answer), kept for benchmarking against the agent. Not used by the API."""

from dataclasses import dataclass
from uuid import UUID

from fastapi.concurrency import run_in_threadpool

from app.retrieval.hybrid import HybridRetriever
from app.services.answering import (
    INSUFFICIENT_EVIDENCE_ANSWER,
    Evidence,
    build_messages,
    is_insufficient,
    parse_citations,
)
from app.services.llm import ChatLLM, TextDelta, Usage


@dataclass
class BaselineResult:
    answer: str
    status: str
    evidence: list[Evidence]
    cited: list[Evidence]
    usage: list[Usage] | None = None


async def baseline_answer(
    question: str,
    *,
    organization_id: UUID,
    document_ids: list[UUID],
    version_ids: list[UUID],
    retriever: HybridRetriever,
    evidence_source,
    llm: ChatLLM,
    max_chunks: int = 8,
    mode: str = "hybrid",
    history: list[dict[str, str]] | None = None,
) -> BaselineResult:
    cands = await run_in_threadpool(
        retriever.retrieve,
        question,
        organization_id=organization_id,
        document_ids=document_ids,
        version_ids=version_ids,
        mode=mode,
    )
    authorized = await evidence_source.authorize(
        [c.chunk_id for c in cands], {c.chunk_id: c.score for c in cands}, include_history=False
    )
    evidence = authorized[:max_chunks]
    if not evidence:
        return BaselineResult(INSUFFICIENT_EVIDENCE_ANSWER, "insufficient_evidence", [], [])
    parts, usage = [], []
    async for event in llm.stream(build_messages(question, evidence, history or [])):
        if isinstance(event, TextDelta):
            parts.append(event.text)
        elif isinstance(event, Usage):
            usage.append(event)
    answer = "".join(parts).strip()
    if is_insufficient(answer):
        return BaselineResult(answer, "insufficient_evidence", evidence, [], usage)
    cited = [evidence[n - 1] for n in parse_citations(answer, len(evidence))]
    return BaselineResult(answer, "answered", evidence, cited, usage)
