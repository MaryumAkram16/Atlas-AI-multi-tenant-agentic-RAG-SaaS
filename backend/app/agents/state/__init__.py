"""Agent state and context.

AgentState is the only thing nodes (and anything model-driven) can change.
AuthContext is created by the server from the verified request, is frozen,
and travels outside the state (in the run config), so neither the model nor
document content can alter who is asking or what they may search.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypedDict
from uuid import UUID

from app.config import Settings
from app.retrieval.authorize import SearchScope
from app.retrieval.hybrid import HybridRetriever
from app.services.answering import Evidence
from app.services.llm import ChatLLM, Usage

# Keys that must never appear in model-editable state.
FORBIDDEN_STATE_KEYS = frozenset(
    {"organization_id", "org_id", "user_id", "role", "scope", "document_ids", "auth", "claims"}
)


@dataclass(frozen=True)
class AuthContext:
    organization_id: UUID
    user_id: UUID
    role: str
    scope: SearchScope


@dataclass(frozen=True)
class AgentDeps:
    auth: AuthContext
    evidence: Any  # EvidenceSource
    retriever: HybridRetriever
    llm: ChatLLM
    reasoner: Any  # HeuristicReasoner | LLMReasoner
    settings: Settings
    emit: Callable[[str, dict], Awaitable[None]]
    deadline: float  # time.monotonic() deadline for the whole run


class AgentState(TypedDict, total=False):
    question: str
    history: list[dict[str, str]]
    intent: str
    plan: dict[str, Any]
    search_queries: list[str]
    attempts: int
    candidates: list[tuple[UUID, float]]
    authorized_count: int
    evidence: list[Evidence]
    evidence_status: str
    assessment_reason: str
    conflicts: list[Any]
    precedence_notes: list[str]
    answer_evidence: list[Evidence]
    answer: str
    feedback: list[str]
    corrections: int
    needs_correction: bool
    verification: dict[str, Any]
    status: str
    usage: list[Usage]
    steps: int
    trace: list[dict[str, Any]]
    halt: str | None
