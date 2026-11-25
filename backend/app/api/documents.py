"""Document and ingestion job endpoints (/v1/organizations/{org_id}/...).

Every route is behind the membership check; document-level access is decided
by Postgres (app_private.document_access) and enforced again by RLS.
"""

import hashlib
import mimetypes
import uuid
from datetime import date
from pathlib import PurePosixPath
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.concurrency import run_in_threadpool
from psycopg import AsyncConnection, errors

from app.auth.dependencies import DB, Org, OrgContext
from app.documents.storage import LocalStorage, object_path
from app.documents.validation import UploadError, safe_filename, validate_upload
from app.repositories import documents as repo
from app.schemas.documents import (
    ChunkPreview,
    DocumentDetail,
    DocumentOut,
    DownloadUrl,
    JobOut,
    UploadAccepted,
    VersionOut,
    Visibility,
)
from app.services import limits

router = APIRouter(prefix="/v1/organizations/{org_id}", tags=["documents"])
files_router = APIRouter(tags=["files"])

UPLOAD_ROLES = frozenset({"owner", "admin", "member"})


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, detail="document not found")


async def _read_upload(request: Request, file: UploadFile) -> tuple[bytes, str]:
    limit = request.app.state.settings.max_upload_bytes
    data = await file.read(limit + 1)
    filename = file.filename or "upload"
    try:
        kind = validate_upload(filename, data, limit)
    except UploadError as exc:
        raise HTTPException(exc.status_code, detail=exc.message) from None
    return data, kind.mime_type


async def _require_write(conn: AsyncConnection, ctx: OrgContext, document_id: UUID) -> dict:
    doc = await repo.get_document(conn, ctx.org_id, document_id)
    if doc is None:
        raise _not_found()
    access = await repo.document_access(conn, document_id)
    if access is None:
        raise _not_found()
    if access != "write":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="you cannot modify this document")
    return doc


async def _document_out(conn: AsyncConnection, doc: dict) -> DocumentOut:
    versions = await repo.versions_by_id(
        conn, [doc["current_version_id"]] if doc["current_version_id"] else []
    )
    current = versions.get(doc["current_version_id"])
    return DocumentOut(**doc, current_version=VersionOut(**current) if current else None)


async def _accepted(conn: AsyncConnection, org_id: UUID, job: dict) -> UploadAccepted:
    doc = await repo.get_document(conn, org_id, job["document_id"])
    version = await repo.get_version(conn, org_id, job["document_id"], job["document_version_id"])
    return UploadAccepted(
        document=await _document_out(conn, doc), version=VersionOut(**version), job=JobOut(**job)
    )


async def _store_then_record(request: Request, path: str, data: bytes, mime: str, record):
    """Write the file first, then the rows; remove the file if the rows fail."""
    storage = request.app.state.storage
    await run_in_threadpool(storage.put, path, data, mime)
    try:
        return await record()
    except BaseException:
        await run_in_threadpool(storage.delete_prefix, path.rsplit("/", 1)[0] + "/")
        raise


# ---------------------------------------------------------------- documents


@router.post("/documents", status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    request: Request,
    response: Response,
    ctx: Org,
    db: DB,
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form(max_length=300)] = None,
    visibility: Annotated[Visibility, Form()] = "organization",
    effective_date: Annotated[date | None, Form()] = None,
    idempotency_key: Annotated[str | None, Header(max_length=200)] = None,
) -> UploadAccepted:
    if ctx.role not in UPLOAD_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="viewers cannot upload documents")
    data, mime = await _read_upload(request, file)
    checksum = hashlib.sha256(data).hexdigest()
    filename = safe_filename(file.filename or "upload")
    job_key = f"upload:{idempotency_key}" if idempotency_key else None

    settings = request.app.state.settings
    async with db.transaction() as conn:
        if job_key and (existing := await repo.job_by_key(conn, ctx.org_id, job_key)):
            response.status_code = status.HTTP_200_OK
            return await _accepted(conn, ctx.org_id, existing)
        await limits.rate_limit(
            conn,
            ctx.org_id,
            "upload",
            settings.rate_limit_upload,
            settings.rate_limit_window_seconds,
        )
        await limits.check_upload(
            conn, settings, ctx.org_id, new_document=True, size_bytes=len(data)
        )
        if dup := await repo.find_duplicate(conn, ctx.org_id, checksum):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "code": "duplicate_document",
                    "message": "This exact file is already in the knowledge base.",
                    "existing_document_id": str(dup),
                },
            )

    doc_id, version_id = uuid.uuid4(), uuid.uuid4()
    path = object_path(ctx.org_id, doc_id, version_id, filename)

    async def record() -> UploadAccepted:
        async with db.transaction() as conn:
            await repo.insert_document(
                conn,
                document_id=doc_id,
                org_id=ctx.org_id,
                owner_id=ctx.user.user_id,
                title=(title or PurePosixPath(filename).stem)[:300],
                visibility=visibility,
            )
            await repo.insert_version(
                conn,
                version_id=version_id,
                org_id=ctx.org_id,
                document_id=doc_id,
                version=1,
                filename=filename,
                mime_type=mime,
                size_bytes=len(data),
                checksum=checksum,
                storage_path=path,
                effective_date=effective_date,
                created_by=ctx.user.user_id,
            )
            job = await repo.insert_job(
                conn,
                org_id=ctx.org_id,
                document_id=doc_id,
                version_id=version_id,
                kind="ingest",
                idempotency_key=job_key or f"ingest:{version_id}",
                max_attempts=settings.job_max_attempts,
                created_by=ctx.user.user_id,
            )
            return await _accepted(conn, ctx.org_id, job)

    try:
        return await _store_then_record(request, path, data, mime, record)
    except errors.UniqueViolation:
        # A concurrent request with the same Idempotency-Key won the race.
        async with db.transaction() as conn:
            existing = await repo.job_by_key(conn, ctx.org_id, job_key) if job_key else None
            if existing is None:
                raise
            response.status_code = status.HTTP_200_OK
            return await _accepted(conn, ctx.org_id, existing)


@router.get("/documents")
async def list_documents(ctx: Org, db: DB) -> list[DocumentOut]:
    async with db.transaction() as conn:
        docs = await repo.list_documents(conn, ctx.org_id)
        current = await repo.versions_by_id(
            conn, [d["current_version_id"] for d in docs if d["current_version_id"]]
        )
    return [
        DocumentOut(
            **d,
            current_version=VersionOut(**current[d["current_version_id"]])
            if d["current_version_id"] in current
            else None,
        )
        for d in docs
    ]


@router.get("/documents/{document_id}")
async def get_document(document_id: UUID, ctx: Org, db: DB) -> DocumentDetail:
    async with db.transaction() as conn:
        doc = await repo.get_document(conn, ctx.org_id, document_id)
        if doc is None:
            raise _not_found()
        versions = await repo.list_versions(conn, document_id)
    by_id = {v["id"]: v for v in versions}
    current = by_id.get(doc["current_version_id"])
    return DocumentDetail(
        **doc,
        current_version=VersionOut(**current) if current else None,
        versions=[VersionOut(**v) for v in versions],
    )


@router.post("/documents/{document_id}/versions", status_code=status.HTTP_202_ACCEPTED)
async def upload_version(
    request: Request,
    document_id: UUID,
    ctx: Org,
    db: DB,
    file: Annotated[UploadFile, File()],
    effective_date: Annotated[date | None, Form()] = None,
) -> UploadAccepted:
    async with db.transaction() as conn:
        doc = await _require_write(conn, ctx, document_id)
    if doc["status"] == "deleting":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="document is being deleted")
    data, mime = await _read_upload(request, file)
    checksum = hashlib.sha256(data).hexdigest()
    settings = request.app.state.settings
    async with db.transaction() as conn:
        await limits.rate_limit(
            conn,
            ctx.org_id,
            "upload",
            settings.rate_limit_upload,
            settings.rate_limit_window_seconds,
        )
        await limits.check_upload(
            conn, settings, ctx.org_id, new_document=False, size_bytes=len(data)
        )
        if dup := await repo.find_duplicate(conn, ctx.org_id, checksum):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "code": "duplicate_document",
                    "message": "This exact file is already in the knowledge base.",
                    "existing_document_id": str(dup),
                },
            )

    filename = safe_filename(file.filename or "upload")
    version_id = uuid.uuid4()
    path = object_path(ctx.org_id, document_id, version_id, filename)

    async def record() -> UploadAccepted:
        async with db.transaction() as conn:
            number = await repo.next_version_number(conn, document_id)
            await repo.insert_version(
                conn,
                version_id=version_id,
                org_id=ctx.org_id,
                document_id=document_id,
                version=number,
                filename=filename,
                mime_type=mime,
                size_bytes=len(data),
                checksum=checksum,
                storage_path=path,
                effective_date=effective_date,
                created_by=ctx.user.user_id,
            )
            job = await repo.insert_job(
                conn,
                org_id=ctx.org_id,
                document_id=document_id,
                version_id=version_id,
                kind="ingest",
                idempotency_key=f"ingest:{version_id}",
                max_attempts=settings.job_max_attempts,
                created_by=ctx.user.user_id,
            )
            return await _accepted(conn, ctx.org_id, job)

    try:
        return await _store_then_record(request, path, data, mime, record)
    except errors.UniqueViolation:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="another version was uploaded at the same time"
        ) from None


@router.post("/documents/{document_id}/reindex", status_code=status.HTTP_202_ACCEPTED)
async def reindex_document(request: Request, document_id: UUID, ctx: Org, db: DB) -> JobOut:
    try:
        async with db.transaction() as conn:
            doc = await _require_write(conn, ctx, document_id)
            if doc["status"] == "deleting":
                raise HTTPException(status.HTTP_409_CONFLICT, detail="document is being deleted")
            versions = await repo.list_versions(conn, document_id)
            target = doc["current_version_id"] or (versions[0]["id"] if versions else None)
            if target is None:
                raise HTTPException(status.HTTP_409_CONFLICT, detail="document has no versions")
            job = await repo.insert_job(
                conn,
                org_id=ctx.org_id,
                document_id=document_id,
                version_id=target,
                kind="reindex",
                idempotency_key=f"reindex:{target}:{uuid.uuid4()}",
                max_attempts=request.app.state.settings.job_max_attempts,
                created_by=ctx.user.user_id,
            )
    except errors.UniqueViolation:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="this version is already being indexed"
        ) from None
    return JobOut(**job)


@router.delete("/documents/{document_id}", status_code=status.HTTP_202_ACCEPTED)
async def delete_document(request: Request, document_id: UUID, ctx: Org, db: DB) -> JobOut:
    # Visibility first (404), then write access (403; viewers never write).
    try:
        async with db.transaction() as conn:
            await _require_write(conn, ctx, document_id)
            if not await repo.mark_deleting(conn, document_id):
                raise HTTPException(status.HTTP_403_FORBIDDEN, detail="not allowed")
            job = await repo.insert_job(
                conn,
                org_id=ctx.org_id,
                document_id=document_id,
                version_id=None,
                kind="delete",
                idempotency_key=f"delete:{document_id}:{uuid.uuid4()}",
                max_attempts=request.app.state.settings.job_max_attempts,
                created_by=ctx.user.user_id,
            )
    except errors.UniqueViolation:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="deletion already in progress"
        ) from None
    return JobOut(**job)


@router.get("/documents/{document_id}/versions/{version_id}/download-url")
async def download_url(
    request: Request, document_id: UUID, version_id: UUID, ctx: Org, db: DB
) -> DownloadUrl:
    async with db.transaction() as conn:
        version = await repo.get_version(conn, ctx.org_id, document_id, version_id)
    if version is None:
        raise _not_found()
    ttl = request.app.state.settings.signed_url_ttl_seconds
    url = await run_in_threadpool(
        request.app.state.storage.signed_url, version["storage_path"], ttl
    )
    return DownloadUrl(url=url, expires_in=ttl)


@router.get("/documents/{document_id}/chunks/{chunk_id}")
async def chunk_preview(document_id: UUID, chunk_id: UUID, ctx: Org, db: DB) -> ChunkPreview:
    """Text of one cited chunk, for source previews (readers only, via RLS)."""
    async with db.transaction() as conn:
        row = await repo.get_chunk(conn, ctx.org_id, document_id, chunk_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="source not found")
    return ChunkPreview(**row)


# ---------------------------------------------------------------- jobs


@router.get("/jobs/{job_id}")
async def get_job(job_id: UUID, ctx: Org, db: DB) -> JobOut:
    async with db.transaction() as conn:
        job = await repo.get_job(conn, ctx.org_id, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="job not found")
    return JobOut(**job)


# ---------------------------------------------------------------- local signed files


@files_router.get("/v1/files/{path:path}")
async def signed_file(request: Request, path: str, expires: int, signature: str) -> Response:
    """Serves local-storage files for signed URLs (dev/test backend only)."""
    storage = request.app.state.storage
    if not isinstance(storage, LocalStorage) or not storage.verify(path, expires, signature):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="invalid or expired link")
    data = await run_in_threadpool(storage.get, path)
    name = path.rsplit("/", 1)[-1]
    return Response(
        data,
        media_type=mimetypes.guess_type(name)[0] or "application/octet-stream",
        # Never render uploaded content inline in the browser.
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )
