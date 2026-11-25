from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class UsageTotals(BaseModel):
    questions: int
    prompt_tokens: int
    completion_tokens: int
    estimated_cost: Decimal | None


class UsageOut(BaseModel):
    period_days: int
    me: UsageTotals
    organization: UsageTotals | None = None
    documents: int | None = None
    storage_bytes: int | None = None
    quota: dict[str, Any] | None = None


class AuditLogOut(BaseModel):
    id: int
    actor_id: UUID | None
    actor_type: str
    action: str
    resource_type: str
    resource_id: UUID | None
    metadata: dict[str, Any]
    created_at: datetime
