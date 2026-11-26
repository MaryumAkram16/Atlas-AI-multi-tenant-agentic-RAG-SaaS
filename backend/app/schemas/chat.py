from datetime import date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.feedback import FeedbackOut


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
    ]
    conversation_id: UUID | None = None
    document_ids: Annotated[list[UUID], Field(max_length=100)] | None = None


class Citation(BaseModel):
    position: int
    chunk_id: UUID
    document_id: UUID
    document_title: str
    version_id: UUID
    version: int
    effective_date: date | None
    section: str | None
    page_start: int | None
    page_end: int | None


class RetrievalStats(BaseModel):
    candidates: int
    authorized: int
    used: int


class UsageOut(BaseModel):
    model: str
    prompt_tokens: int
    completion_tokens: int


AnswerStatus = Literal[
    "answered", "insufficient_evidence", "clarification_needed", "direct", "error"
]
EvidenceStatus = Literal["sufficient", "weak", "none", "not_needed"]


class ConflictDocument(BaseModel):
    document_id: UUID
    title: str
    policy_id: str | None
    effective_date: date | None
    values: list[str]
    status: Literal["current", "superseded", "outdated", "exception"]
    reason: str | None


class Conflict(BaseModel):
    topic: str
    resolution: Literal["resolved", "ambiguous", "unresolved"]
    notes: list[str]
    documents: list[ConflictDocument]


class ChatResponse(BaseModel):
    conversation_id: UUID
    message_id: UUID
    answer: str
    status: AnswerStatus
    evidence_status: EvidenceStatus
    citations: list[Citation]
    conflicts: list[Conflict]
    retrieval_attempts: int
    trace_id: str
    retrieval: RetrievalStats
    usage: UsageOut | None
    latency_ms: int
    # "Why this answer?": decisions and source versions, never document text.
    explanation: dict[str, Any] | None = None


class ConversationOut(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    id: UUID
    role: Literal["user", "assistant"]
    content: str
    status: AnswerStatus | None
    created_at: datetime
    citations: list[Citation]
    evidence_status: EvidenceStatus | None = None
    conflicts: list[Conflict] = []
    retrieval_attempts: int | None = None
    trace_id: str | None = None
    explanation: dict[str, Any] | None = None
    # Your own rating of this answer, if any.
    feedback: FeedbackOut | None = None


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]
