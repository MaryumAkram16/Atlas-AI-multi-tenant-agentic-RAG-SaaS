from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

Rating = Literal["up", "down"]
Reason = Literal["incorrect", "missing_information", "wrong_citation", "outdated", "other"]


class FeedbackIn(BaseModel):
    rating: Rating
    reason: Reason | None = None
    comment: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _consistent(self):
        if self.rating == "up" and self.reason is not None:
            raise ValueError("a reason is only given with a thumbs down")
        if self.comment is not None:
            self.comment = self.comment.strip() or None
        return self


class FeedbackOut(BaseModel):
    message_id: UUID
    rating: Rating
    reason: Reason | None
    comment: str | None
    created_at: datetime
    updated_at: datetime


class FeedbackReviewOut(FeedbackOut):
    user_id: UUID
    email: str | None
    question: str
    answer_status: str
