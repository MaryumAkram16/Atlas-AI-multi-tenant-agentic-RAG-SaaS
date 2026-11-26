from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

Visibility = Literal["organization", "restricted"]
Permission = Literal["read", "write"]


class VersionOut(BaseModel):
    id: UUID
    document_id: UUID
    version: int
    filename: str
    mime_type: str
    size_bytes: int
    checksum: str
    effective_date: date | None
    status: str
    chunk_count: int | None
    error: str | None
    created_at: datetime
    published_at: datetime | None


class DocumentOut(BaseModel):
    id: UUID
    organization_id: UUID
    owner_id: UUID
    title: str
    visibility: Visibility
    status: str
    created_at: datetime
    updated_at: datetime
    # The caller's own access ("read" or "write"), decided by Postgres.
    access: Permission | None = None
    # Latest ingest/reindex job: queued | running | succeeded | failed.
    job_status: str | None = None
    current_version: VersionOut | None = None


class DocumentDetail(DocumentOut):
    versions: list[VersionOut]


class JobOut(BaseModel):
    id: UUID
    organization_id: UUID
    document_id: UUID | None
    document_version_id: UUID | None
    kind: str
    status: str
    attempts: int
    max_attempts: int
    run_after: datetime
    last_error: str | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None


class UploadAccepted(BaseModel):
    document: DocumentOut
    version: VersionOut
    job: JobOut


class ChunkPreview(BaseModel):
    chunk_id: UUID
    document_id: UUID
    document_title: str
    version_id: UUID
    version: int
    effective_date: date | None
    section: str | None
    page_start: int | None
    page_end: int | None
    content: str
    is_current: bool = True
    current_version: int | None = None
    current_effective_date: date | None = None


class DownloadUrl(BaseModel):
    url: str
    expires_in: int


class DocumentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    visibility: Visibility | None = None

    @model_validator(mode="after")
    def _not_empty(self):
        if self.title is None and self.visibility is None:
            raise ValueError("nothing to update")
        if self.title is not None:
            self.title = self.title.strip()
            if not self.title:
                raise ValueError("title cannot be blank")
        return self


class PermissionGrant(BaseModel):
    permission: Permission


class DocumentPermissionOut(BaseModel):
    user_id: UUID
    email: str | None
    role: str
    member_status: str
    permission: Permission
    granted_by: UUID
    created_at: datetime
