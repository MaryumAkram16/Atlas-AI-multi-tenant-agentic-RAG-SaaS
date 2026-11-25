"""The bounded LangGraph agent.

validate_context -> classify_intent -+-> finalize (greeting / clarification)
                                     +-> plan_retrieval -> decompose_query
  -> retrieve_documents -> validate_permissions -> rerank_results -> assess_evidence
       weak/none: rewrite_query -> retrieve_documents (max AGENT_MAX_REWRITES), then abstain
       sufficient: detect_conflicts -> compare_versions -> generate_answer -> verify_citations
            failed check: generate_answer again (max AGENT_MAX_CORRECTIONS), then
            keep supported sentences or abstain
  -> finalize_response

Bounded by AGENT_MAX_STEPS (state guard plus LangGraph's recursion limit),
AGENT_TIMEOUT_SECONDS for the whole run, and LLM/evidence token limits.
"""

import asyncio
import time
import uuid
from functools import lru_cache

from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph

from app.agents import nodes as n
from app.agents.state import AgentDeps, AgentState

FINAL = "finalize_response"


def _halted(state: AgentState) -> bool:
    return bool(state.get("halt"))


def after_classify(state: AgentState) -> str:
    if _halted(state):
        return FINAL
    if state["intent"] in ("greeting", "clarify"):
        return FINAL
    return "plan_retrieval"  # knowledge and comparison questions must retrieve


def after_assess(state: AgentState, max_rewrites: int, enable_rewrite: bool = True) -> str:
    if _halted(state):
        return FINAL
    if state.get("evidence_status") == "sufficient":
        return "detect_conflicts"
    if not enable_rewrite:
        # Ablation: answer from whatever was found (abstain only with no evidence).
        return FINAL if state.get("evidence_status") == "none" else "detect_conflicts"
    if state.get("attempts", 0) <= max_rewrites:
        return "rewrite_query"
    return FINAL


def after_verify(state: AgentState) -> str:
    if _halted(state):
        return FINAL
    return "generate_answer" if state.get("needs_correction") else FINAL


def _guard(next_node: str):
    return lambda state: FINAL if _halted(state) else next_node


@lru_cache(maxsize=8)
def build_graph(max_rewrites: int, enable_rewrite: bool = True):
    g = StateGraph(AgentState)
    for fn in (
        n.validate_context,
        n.classify_intent,
        n.plan_retrieval,
        n.decompose_query,
        n.retrieve_documents,
        n.validate_permissions,
        n.rerank_results,
        n.assess_evidence,
        n.rewrite_query,
        n.detect_conflicts_node,
        n.compare_versions,
        n.generate_answer,
        n.verify_citations,
        n.finalize_response,
    ):
        g.add_node(fn.node_name, fn)

    g.add_edge(START, "validate_context")
    g.add_conditional_edges("validate_context", _guard("classify_intent"))
    g.add_conditional_edges("classify_intent", after_classify)
    for a, b in [
        ("plan_retrieval", "decompose_query"),
        ("decompose_query", "retrieve_documents"),
        ("retrieve_documents", "validate_permissions"),
        ("validate_permissions", "rerank_results"),
        ("rerank_results", "assess_evidence"),
        ("rewrite_query", "retrieve_documents"),
        ("detect_conflicts", "compare_versions"),
        ("compare_versions", "generate_answer"),
        ("generate_answer", "verify_citations"),
    ]:
        g.add_conditional_edges(a, _guard(b))
    g.add_conditional_edges(
        "assess_evidence", lambda s: after_assess(s, max_rewrites, enable_rewrite)
    )
    g.add_conditional_edges("verify_citations", after_verify)
    g.add_edge(FINAL, END)
    return g.compile()


async def run_agent(
    question: str, history: list[dict[str, str]], deps: AgentDeps
) -> tuple[AgentState, str]:
    """Returns the final state and a trace ID."""
    trace_id = uuid.uuid4().hex
    settings = deps.settings
    initial: AgentState = {
        "question": question,
        "history": history,
        "steps": 0,
        "attempts": 0,
        "corrections": 0,
        "trace": [],
        "usage": [],
    }
    graph = build_graph(settings.agent_max_rewrites, settings.agent_enable_rewrite)
    config = {
        "configurable": {"deps": deps},
        "recursion_limit": settings.agent_max_steps + 10,
    }
    remaining = max(0.1, deps.deadline - time.monotonic())
    try:
        state = await asyncio.wait_for(graph.ainvoke(initial, config=config), timeout=remaining)
    except TimeoutError:
        state = {
            **initial,
            "status": "error",
            "answer": n.HALT_REPLIES["timeout"],
            "halt": "timeout",
        }
    except GraphRecursionError:
        state = {
            **initial,
            "status": "error",
            "answer": n.HALT_REPLIES["step_limit"],
            "halt": "step_limit",
        }
    return state, trace_id
