"""Ingestion worker: claims jobs from the Postgres queue and runs them.

ingest/reindex: storage -> parse -> chunk -> embed (dense + BM25) -> Qdrant
upsert -> validate the indexed count -> publish atomically in Postgres.
delete: remove vectors and stored files, then the rows.

Every database transaction is pinned to the job's tenant (app.organization_id),
so RLS confines the worker to one organization at a time. Logs carry IDs and
statuses only, never document text.
"""

import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date

import psycopg
from psycopg.rows import dict_row

from app.config import Settings
from app.db.urls import libpq_url
from app.documents.storage import ObjectStorage, build_storage
from app.documents.validation import validate_upload
from app.ingestion.chunking import Chunk, chunk_blocks
from app.ingestion.parsing import parse_document
from app.ingestion.tokenizer import Tokenizer, get_tokenizer
from app.retrieval.embeddings import Embedder, build_embedder
from app.retrieval.index import IndexPoint, VectorIndex
from app.retrieval.sparse import bm25_document_vector
from app.workers import queue
from app.workers.queue import Job

logger = logging.getLogger("app.worker")

CHUNK_NAMESPACE = uuid.UUID("5b2f0c7e-8d1a-4c39-9f0e-6a1d2b3c4d5e")


class PermanentJobError(Exception):
    """Retrying cannot help (deleted document, no extractable text, ...)."""


def chunk_id(version_id: uuid.UUID, index: int) -> uuid.UUID:
    """Deterministic, so reprocessing overwrites instead of duplicating."""
    return uuid.uuid5(CHUNK_NAMESPACE, f"{version_id}:{index}")


def embedding_input(chunk: Chunk) -> str:
    return f"{chunk.section}\n\n{chunk.content}" if chunk.section else chunk.content


class IngestionWorker:
    def __init__(
        self,
        *,
        conninfo: str,
        worker_id: str,
        storage: ObjectStorage,
        embedder: Embedder,
        index: VectorIndex,
        tokenizer: Tokenizer,
        chunk_tokens: int,
        chunk_overlap: int,
        lease_seconds: int,
        backoff_base: float,
        backoff_cap: float,
    ) -> None:
        self.conn = psycopg.connect(conninfo, autocommit=True, row_factory=dict_row)
        self.worker_id = worker_id
        self.storage = storage
        self.embedder = embedder
        self.index = index
        self.tokenizer = tokenizer
        self.chunk_tokens = chunk_tokens
        self.chunk_overlap = chunk_overlap
        self.lease_seconds = lease_seconds
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap

    @classmethod
    def from_settings(cls, settings: Settings, worker_id: str) -> "IngestionWorker":
        return cls(
            conninfo=libpq_url(settings.worker_database_url.get_secret_value()),
            worker_id=worker_id,
            storage=build_storage(settings),
            embedder=build_embedder(settings),
            index=VectorIndex.from_settings(settings),
            tokenizer=get_tokenizer(settings.tokenizer),
            chunk_tokens=settings.chunk_tokens,
            chunk_overlap=settings.chunk_overlap_tokens,
            lease_seconds=settings.job_lease_seconds,
            backoff_base=settings.job_backoff_base_seconds,
            backoff_cap=settings.job_backoff_max_seconds,
        )

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def tenant(self, org_id: uuid.UUID) -> Iterator[psycopg.Connection]:
        with self.conn.transaction():
            self.conn.execute("SELECT set_config('app.organization_id', %s, true)", (str(org_id),))
            yield self.conn

    # ------------------------------------------------------------------ loop

    def run_once(self) -> bool:
        """Claim and process one job. Returns False when nothing is due."""
        job = queue.claim(self.conn, self.worker_id, self.lease_seconds)
        if job is None:
            return False
        log = {"job_id": str(job.id), "kind": job.kind, "org_id": str(job.organization_id)}
        logger.info("job claimed attempt=%s %s", job.attempts, log)
        try:
            if job.attempts > job.max_attempts:
                raise PermanentJobError("attempts exhausted after lease expiry")
            if job.kind == "delete":
                self._delete(job)
            else:
                self._ingest(job)
            logger.info("job succeeded %s", log)
        except Exception as exc:
            self._handle_failure(job, exc)
            logger.warning(
                "job failed attempt=%s error=%s %s", job.attempts, type(exc).__name__, log
            )
        return True

    # ------------------------------------------------------------------ ingest

    def _ingest(self, job: Job) -> None:
        org = job.organization_id
        with self.tenant(org) as conn:
            version = conn.execute(
                "SELECT v.id, v.document_id, v.version, v.filename, v.storage_path, v.status,"
                "       v.effective_date, d.status AS document_status"
                " FROM document_versions v JOIN documents d ON d.id = v.document_id"
                " WHERE v.id = %s AND v.document_id = %s",
                (job.document_version_id, job.document_id),
            ).fetchone()
            if version is None or version["document_status"] == "deleting":
                raise PermanentJobError("document no longer exists")
            if version["status"] in ("pending", "failed"):
                conn.execute(
                    "UPDATE document_versions SET status = 'processing', error = NULL"
                    " WHERE id = %s",
                    (version["id"],),
                )
            previous_ids = {
                r["id"]
                for r in conn.execute(
                    "SELECT id FROM document_chunks WHERE document_version_id = %s",
                    (version["id"],),
                )
            }

        data = self.storage.get(version["storage_path"])
        kind = validate_upload(version["filename"], data, max_bytes=len(data))
        parsed = parse_document(data, kind.parser)
        chunks = chunk_blocks(
            parsed.blocks,
            self.tokenizer,
            max_tokens=self.chunk_tokens,
            overlap=self.chunk_overlap,
        )
        if not chunks:
            raise PermanentJobError("no extractable text")

        ids = [chunk_id(version["id"], c.index) for c in chunks]
        with self.tenant(org) as conn:
            conn.execute(
                "DELETE FROM document_chunks WHERE document_version_id = %s", (version["id"],)
            )
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO document_chunks (id, organization_id, document_id,"
                    " document_version_id, chunk_index, content, token_count, page_start,"
                    " page_end, section) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    [
                        (
                            cid,
                            org,
                            version["document_id"],
                            version["id"],
                            c.index,
                            c.content,
                            c.token_count,
                            c.page_start,
                            c.page_end,
                            c.section,
                        )
                        for cid, c in zip(ids, chunks, strict=True)
                    ],
                )

        texts = [embedding_input(c) for c in chunks]
        dense = self.embedder.embed(texts)
        if len(dense) != len(chunks):
            raise RuntimeError("embedding count mismatch")
        self.index.upsert(
            [
                IndexPoint(
                    id=cid,
                    dense=vec,
                    sparse=bm25_document_vector(text),
                    organization_id=org,
                    document_id=version["document_id"],
                    version_id=version["id"],
                    chunk_index=c.index,
                )
                for cid, c, vec, text in zip(ids, chunks, dense, texts, strict=True)
            ]
        )
        stale = previous_ids - set(ids)
        if stale:
            self.index.delete_points(list(stale))

        indexed = self.index.count(organization_id=org, version_id=version["id"])
        if indexed != len(chunks):
            raise RuntimeError(f"index validation failed: {indexed} of {len(chunks)} points")

        self._publish(job, version, len(chunks), parsed.effective_date)

    def _publish(self, job: Job, version: dict, chunk_count: int, detected: date | None) -> None:
        org = job.organization_id
        with self.tenant(org) as conn:
            doc = conn.execute(
                "SELECT d.status, cur.version AS current_number"
                " FROM documents d"
                " LEFT JOIN document_versions cur ON cur.id = d.current_version_id"
                " WHERE d.id = %s FOR UPDATE OF d",
                (version["document_id"],),
            ).fetchone()
            if doc is None or doc["status"] == "deleting":
                self.index.delete_version(organization_id=org, version_id=version["id"])
                raise PermanentJobError("document deleted during ingestion")

            conn.execute(
                "UPDATE document_chunks SET embedding_status = 'indexed'"
                " WHERE document_version_id = %s",
                (version["id"],),
            )
            newer_is_current = (
                doc["current_number"] is not None and doc["current_number"] > version["version"]
            )
            if newer_is_current:
                # Indexed for history, but a newer version is already live.
                conn.execute(
                    "UPDATE document_versions SET status = 'superseded', chunk_count = %s,"
                    " effective_date = coalesce(effective_date, %s) WHERE id = %s",
                    (chunk_count, detected, version["id"]),
                )
            else:
                conn.execute(
                    "UPDATE document_versions SET status = 'superseded'"
                    " WHERE document_id = %s AND status = 'published' AND id <> %s",
                    (version["document_id"], version["id"]),
                )
                conn.execute(
                    "UPDATE document_versions SET status = 'published', chunk_count = %s,"
                    " error = NULL, effective_date = coalesce(effective_date, %s),"
                    " published_at = coalesce(published_at, now()) WHERE id = %s",
                    (chunk_count, detected, version["id"]),
                )
                conn.execute(
                    "UPDATE documents SET current_version_id = %s, status = 'ready' WHERE id = %s",
                    (version["id"], version["document_id"]),
                )
            self._mark_succeeded(conn, job)

    # ------------------------------------------------------------------ delete

    def _delete(self, job: Job) -> None:
        org, doc_id = job.organization_id, job.document_id
        with self.tenant(org) as conn:
            doc = (
                conn.execute(
                    "SELECT id FROM documents WHERE id = %s AND status = 'deleting'", (doc_id,)
                ).fetchone()
                if doc_id
                else None
            )
        if doc is not None:
            self.index.delete_document(organization_id=org, document_id=doc_id)
            self.storage.delete_prefix(f"{org}/{doc_id}/")
        with self.tenant(org) as conn:
            if doc is not None:
                conn.execute(
                    "DELETE FROM documents WHERE id = %s AND status = 'deleting'", (doc_id,)
                )
            self._mark_succeeded(conn, job)

    # ------------------------------------------------------------------ status

    def _mark_succeeded(self, conn: psycopg.Connection, job: Job) -> None:
        conn.execute(
            "UPDATE ingestion_jobs SET status = 'succeeded', finished_at = now(),"
            " last_error = NULL, locked_at = NULL, locked_by = NULL WHERE id = %s",
            (job.id,),
        )

    def _handle_failure(self, job: Job, exc: Exception) -> None:
        error = queue.sanitize_error(exc)
        permanent = isinstance(exc, PermanentJobError) or job.attempts >= job.max_attempts
        try:
            with self.tenant(job.organization_id) as conn:
                if not permanent:
                    delay = queue.backoff_seconds(
                        job.attempts, base=self.backoff_base, cap=self.backoff_cap
                    )
                    conn.execute(
                        "UPDATE ingestion_jobs SET status = 'queued', last_error = %s,"
                        " run_after = now() + make_interval(secs => %s),"
                        " locked_at = NULL, locked_by = NULL WHERE id = %s",
                        (error, delay, job.id),
                    )
                    return
                conn.execute(
                    "UPDATE ingestion_jobs SET status = 'failed', last_error = %s,"
                    " finished_at = now(), locked_at = NULL, locked_by = NULL WHERE id = %s",
                    (error, job.id),
                )
                if job.kind != "delete" and job.document_version_id is not None:
                    self._fail_version(conn, job, error)
        except Exception:
            # The lease will expire and the job will be retried.
            logger.exception("could not record job failure job_id=%s", job.id)

    def _fail_version(self, conn: psycopg.Connection, job: Job, error: str) -> None:
        row = conn.execute(
            "UPDATE document_versions SET status = 'failed', error = %s"
            " WHERE id = %s AND status IN ('pending', 'processing') RETURNING id",
            (error, job.document_version_id),
        ).fetchone()
        if row is None:
            return  # a published version that failed to reindex stays live
        conn.execute(
            "DELETE FROM document_chunks WHERE document_version_id = %s", (job.document_version_id,)
        )
        conn.execute(
            "UPDATE documents SET status = 'failed'"
            " WHERE id = %s AND current_version_id IS NULL AND status = 'processing'",
            (job.document_id,),
        )
        try:
            self.index.delete_version(
                organization_id=job.organization_id, version_id=job.document_version_id
            )
        except Exception:
            logger.warning("could not remove vectors for failed version job_id=%s", job.id)
