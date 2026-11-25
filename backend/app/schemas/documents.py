from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

Visibility = Literal["organization", "restricted"]


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


class DownloadUrl(BaseModel):
    url: str
    expires_in: int
