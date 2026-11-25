from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class CaseIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    expected_facts: list[str] = Field(default_factory=list, max_length=20)
    expected_document_ids: list[UUID] = Field(default_factory=list, max_length=20)
    should_abstain: bool = False

    @field_validator("question")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("question cannot be blank")
        return v

    @field_validator("expected_facts")
    @classmethod
    def _facts(cls, v: list[str]) -> list[str]:
        facts = [f.strip() for f in v if f.strip()]
        if any(len(f) > 300 for f in facts):
            raise ValueError("facts are limited to 300 characters")
        return facts

    @model_validator(mode="after")
    def _consistent(self):
        if self.should_abstain and self.expected_facts:
            raise ValueError("a case that should abstain cannot expect facts")
        if not (self.should_abstain or self.expected_facts or self.expected_document_ids):
            raise ValueError("give expected facts, expected documents, or should_abstain")
        self.expected_document_ids = list(dict.fromkeys(self.expected_document_ids))
        return self


class DatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    cases: list[CaseIn] = Field(default_factory=list, max_length=500)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name cannot be blank")
        return v


class CasesAdd(BaseModel):
    cases: list[CaseIn] = Field(min_length=1, max_length=500)


class CaseOut(BaseModel):
    id: UUID
    question: str
    expected_facts: list[str]
    expected_document_ids: list[UUID]
    should_abstain: bool
    created_at: datetime


class DatasetOut(BaseModel):
    id: UUID
    name: str
    description: str | None
    case_count: int
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class DatasetDetail(DatasetOut):
    cases: list[CaseOut]


class RunCreate(BaseModel):
    dataset_id: UUID


class RunOut(BaseModel):
    id: UUID
    dataset_id: UUID | None
    dataset_name: str
    status: Literal["running", "succeeded", "failed"]
    config: dict[str, Any]
    metrics: dict[str, Any] | None
    case_count: int
    error: str | None
    created_by: UUID
    created_at: datetime
    finished_at: datetime | None


class ResultOut(BaseModel):
    case_id: UUID | None
    position: int
    question: str
    status: str
    answer: str
    abstained: bool
    fact_hit: bool | None
    abstention_correct: bool | None
    evidence_hit: bool | None
    cited_document_ids: list[UUID]
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int


class RunDetail(RunOut):
    results: list[ResultOut]
    # Results whose source documents you cannot read are withheld.
    hidden_results: int
