"""Agent nodes. Each node receives the state and the immutable deps and
returns a partial state update. Nodes never read tenant identity from state."""

import dataclasses
import logging
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi.concurrency import run_in_threadpool
from langchain_core.runnables import RunnableConfig

from app.agents.state import FORBIDDEN_STATE_KEYS, AgentDeps, AgentState, AuthContext
from app.agents.tools.conflicts import detect_conflicts, excluded_documents, parse_meta, resolve
from app.agents.tools.reasoner import classify, coverage
from app.agents.tools.text import policy_ids, salient_terms
from app.agents.tools.verify import verify
from app.observability.tracing import span
from app.retrieval.fusion import rrf_fuse
from app.services.answering import (
    INSUFFICIENT_EVIDENCE_ANSWER,
    build_messages,
    is_insufficient,
)
from app.services.llm import TextDelta, Usage

logger = logging.getLogger("app.agent")

GREETING_REPLY = (
    "Hello! Ask me a question about your organization's documents and I'll answer with citations."
)
CLARIFY_REPLY = "Could you say a bit more about what you're looking for?"
HALT_REPLIES = {
    "step_limit": "I couldn't finish answering within the allowed number of steps.",
    "timeout": "I couldn't finish answering in time. Please try again.",
}


class ContextViolation(Exception):
    """The server-created auth context is missing, mutable or leaked into state."""


NodeFn = Callable[[AgentState, AgentDeps], Awaitable[dict[str, Any]]]


def node(name: str, *, guarded: bool = True):
    """Step counting, deadline/step guards, progress events and timing."""

    def decorate(fn: NodeFn):
        # No functools.wraps: LangGraph inspects the signature to pass `config`.
        async def wrapped(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
            deps: AgentDeps = config["configurable"]["deps"]
            steps = state.get("steps", 0) + 1
            if guarded:
                if steps > deps.settings.agent_max_steps:
                    return {"steps": steps, "halt": "step_limit"}
                if time.monotonic() > deps.deadline:
                    return {"steps": steps, "halt": "timeout"}
            await deps.emit("step", {"node": name})
            started = time.perf_counter()
            with span(f"agent.{name}", node=name, step=steps) as s:
                update = await fn(state, deps) or {}
                for key in ("intent", "evidence_status", "status", "attempts"):
                    if key in update:
                        s.set_attribute(f"agent.{key}", update[key])
            elapsed = round((time.perf_counter() - started) * 1000, 1)
            update["steps"] = steps
            update["trace"] = [*state.get("trace", []), {"node": name, "ms": elapsed}]
            return update

        wrapped.__name__ = wrapped.__qualname__ = fn.__name__
        wrapped.__doc__ = fn.__doc__
        wrapped.node_name = name
        return wrapped

    return decorate


# ---------------------------------------------------------------- context & intent


@node("validate_context")
async def validate_context(state: AgentState, deps: AgentDeps) -> dict:
    auth = deps.auth
    if not isinstance(auth, AuthContext) or not dataclasses.is_dataclass(auth):
        raise ContextViolation("missing auth context")
    if not type(auth).__dataclass_params__.frozen:
        raise ContextViolation("auth context must be immutable")
    leaked = FORBIDDEN_STATE_KEYS & set(state)
    if leaked:
        raise ContextViolation(f"identity keys in agent state: {sorted(leaked)}")
    question = state.get("question", "")
    if not isinstance(question, str) or not 0 < len(question) <= 2000:
        raise ContextViolation("invalid question")
    return {}


@node("classify_intent")
async def classify_intent(state: AgentState, deps: AgentDeps) -> dict:
    intent = classify(state["question"])
    if intent == "greeting":
        return {
            "intent": intent,
            "answer": GREETING_REPLY,
            "status": "direct",
            "evidence_status": "not_needed",
        }
    if intent == "clarify":
        return {
            "intent": intent,
            "answer": CLARIFY_REPLY,
            "status": "clarification_needed",
            "evidence_status": "not_needed",
        }
    return {"intent": intent}


# ---------------------------------------------------------------- retrieval


@node("plan_retrieval")
async def plan_retrieval(state: AgentState, deps: AgentDeps) -> dict:
    return {
        "plan": {
            "strategy": "hybrid",
            "include_history": state["intent"] == "comparison",
            "exact_ids": policy_ids(state["question"]),
        }
    }


@node("decompose_query")
async def decompose_query(state: AgentState, deps: AgentDeps) -> dict:
    question = state["question"]
    subs = await deps.reasoner.decompose(question)
    queries = list(dict.fromkeys([question, *subs, *state["plan"]["exact_ids"]]))
    return {"search_queries": queries}


@node("retrieve_documents")
async def retrieve_documents(state: AgentState, deps: AgentDeps) -> dict:
    scope = deps.auth.scope
    include_history = state["plan"]["include_history"]
    versions = scope.history_version_ids if include_history else scope.version_ids
    rankings = []
    for query in state["search_queries"]:
        cands = await run_in_threadpool(
            deps.retriever.retrieve,
            query,
            organization_id=deps.auth.organization_id,  # from the frozen context only
            document_ids=list(scope.document_ids),
            version_ids=list(versions),
        )
        rankings.append([c.chunk_id for c in cands])
    limit = deps.settings.retrieval_fused_k * (2 if len(rankings) > 1 else 1)
    fused = rrf_fuse(rankings, k=deps.settings.rrf_k, limit=limit)
    return {"attempts": state.get("attempts", 0) + 1, "candidates": fused}


@node("validate_permissions")
async def validate_permissions(state: AgentState, deps: AgentDeps) -> dict:
    candidates = state.get("candidates", [])
    evidence = await deps.evidence.authorize(
        [cid for cid, _ in candidates],
        dict(candidates),
        include_history=state["plan"]["include_history"],
    )
    return {"evidence": evidence, "authorized_count": len(evidence)}


@node("rerank_results")
async def rerank_results(state: AgentState, deps: AgentDeps) -> dict:
    """Lightweight reranker (fused score + topical coverage + exact IDs).
    A cross-encoder can replace this if the benchmark justifies its cost."""
    evidence = state.get("evidence", [])
    if not evidence:
        return {"evidence": []}
    question, ids = state["question"], state["plan"]["exact_ids"]
    top = max(e.score for e in evidence) or 1.0
    # Documents whose title block names a policy ID from the question get the
    # boost on every chunk, not just the chunk that repeats the ID.
    named_docs = {
        e.document_id
        for e in evidence
        for i in ids
        if re.search(rf"(?:Policy|Document)\s+ID:\s*{re.escape(i)}\b", e.content, re.IGNORECASE)
    }

    def score(e):
        s = 0.5 * (e.score / top) + 0.5 * coverage(question, [e])
        if e.document_id in named_docs:
            s += 0.2
        elif any(i in e.content for i in ids):
            s += 0.1
        return s

    seen, ranked = set(), []
    for e in sorted(evidence, key=score, reverse=True):
        key = e.content.strip()
        if key not in seen:
            seen.add(key)
            ranked.append(e)
    budget, kept = deps.settings.agent_max_evidence_tokens, []
    for e in ranked[: deps.settings.answer_max_chunks]:
        cost = len(e.content) // 4 + 20
        if kept and cost > budget:
            break
        kept.append(e)
        budget -= cost
    return {"evidence": kept}


@node("assess_evidence")
async def assess_evidence(state: AgentState, deps: AgentDeps) -> dict:
    assessment = await deps.reasoner.assess(state["question"], state.get("evidence", []))
    return {"evidence_status": assessment.status, "assessment_reason": assessment.reason}


@node("rewrite_query")
async def rewrite_query(state: AgentState, deps: AgentDeps) -> dict:
    rewritten = await deps.reasoner.rewrite(state["question"], state.get("attempts", 0))
    return {"search_queries": list(dict.fromkeys([rewritten, *state["plan"]["exact_ids"]]))}


# ---------------------------------------------------------------- conflicts


@node("detect_conflicts")
async def detect_conflicts_node(state: AgentState, deps: AgentDeps) -> dict:
    evidence = state["evidence"]
    headers = await deps.evidence.headers(list({e.version_id for e in evidence}))
    metas = {}
    for e in evidence:
        if e.document_id not in metas:
            texts = [x.content for x in evidence if x.document_id == e.document_id]
            header = headers.get(e.version_id)
            metas[e.document_id] = parse_meta(e, header, [*texts, header or ""])
    conflicts = detect_conflicts(evidence, metas, salient_terms(state["question"]))
    return {"conflicts": [(c, metas) for c in conflicts]}


@node("compare_versions")
async def compare_versions(state: AgentState, deps: AgentDeps) -> dict:
    resolved = [resolve(c, metas) for c, metas in state.get("conflicts", [])]
    notes = [n for c in resolved for n in c.notes]
    evidence = state["evidence"]
    if state["intent"] == "comparison":
        answer_evidence = evidence  # comparisons need every version, flagged by notes
    else:
        # A policy the user names explicitly is never excluded, even if superseded.
        named = set(state["plan"]["exact_ids"])
        keep = {
            d["document_id"]
            for c in resolved
            for d in [x.__dict__ for x in c.documents]
            if d["policy_id"] in named
        }
        excluded = excluded_documents(resolved) - keep
        answer_evidence = [e for e in evidence if e.document_id not in excluded] or evidence
    return {
        "conflicts": [c.as_dict() for c in resolved],
        "precedence_notes": notes,
        "answer_evidence": answer_evidence,
    }


# ---------------------------------------------------------------- answer


@node("generate_answer")
async def generate_answer(state: AgentState, deps: AgentDeps) -> dict:
    messages = build_messages(
        state["question"],
        state["answer_evidence"],
        state.get("history", []),
        notes=state.get("precedence_notes"),
        feedback=state.get("feedback"),
    )
    parts, usage = [], list(state.get("usage", []))
    with span("llm.generate", model=deps.llm.name, sources=len(state["answer_evidence"])) as s:
        async for event in deps.llm.stream(messages):
            if isinstance(event, TextDelta):
                parts.append(event.text)
            elif isinstance(event, Usage):
                usage.append(event)
                s.set_attribute("llm.prompt_tokens", event.prompt_tokens)
                s.set_attribute("llm.completion_tokens", event.completion_tokens)
    return {"answer": "".join(parts).strip(), "usage": usage, "needs_correction": False}


def _source_texts(state: AgentState) -> list[str]:
    return [f"{e.document_title} {e.section or ''} {e.content}" for e in state["answer_evidence"]]


@node("verify_citations")
async def verify_citations(state: AgentState, deps: AgentDeps) -> dict:
    answer = state.get("answer", "")
    if is_insufficient(answer):
        return {"status": "insufficient_evidence", "verification": {"ok": True, "abstained": True}}
    result = verify(answer, _source_texts(state))
    if result.ok:
        return {"status": "answered", "verification": {"ok": True, "problems": []}}
    corrections = state.get("corrections", 0)
    if corrections < deps.settings.agent_max_corrections:
        return {
            "needs_correction": True,
            "corrections": corrections + 1,
            "feedback": result.problems[:5],
            "verification": {"ok": False, "problems": result.problems[:5]},
        }
    # Out of corrections: keep only supported, cited sentences, or abstain.
    cited = [s for s in result.supported if "[" in s]
    if cited:
        return {
            "answer": " ".join(result.supported),
            "status": "answered",
            "verification": {"ok": False, "partial": True, "problems": result.problems[:5]},
        }
    return {
        "answer": INSUFFICIENT_EVIDENCE_ANSWER,
        "status": "insufficient_evidence",
        "verification": {"ok": False, "abstained": True, "problems": result.problems[:5]},
    }


@node("finalize_response", guarded=False)
async def finalize_response(state: AgentState, deps: AgentDeps) -> dict:
    halt = state.get("halt")
    if halt:
        return {"status": "error", "answer": HALT_REPLIES[halt]}
    if state.get("status") in ("direct", "clarification_needed"):
        return {}
    if state.get("intent") in ("knowledge", "comparison") and not state.get("attempts"):
        # Invariant: knowledge questions always retrieve.
        logger.error("knowledge question reached finalize without retrieval")
        return {"status": "error", "answer": "The answer could not be generated."}
    if state.get("status") in ("answered", "insufficient_evidence"):
        return {}
    # Reached without an answer: evidence stayed weak after the rewrite limit.
    return {"status": "insufficient_evidence", "answer": INSUFFICIENT_EVIDENCE_ANSWER}
