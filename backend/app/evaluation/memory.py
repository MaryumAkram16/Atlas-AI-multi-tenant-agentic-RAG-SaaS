"""In-memory corpus for benchmarks and graph tests: the same parsing and
chunking as production, held in memory instead of Postgres."""

import uuid
from collections.abc import Sequence
from pathlib import Path

from app.documents.validation import validate_upload
from app.ingestion.chunking import chunk_blocks
from app.ingestion.parsing import parse_document
from app.ingestion.tokenizer import Tokenizer
from app.services.answering import Evidence

NS = uuid.UUID("1f0c9b7e-6a55-4d0e-9d8c-3c2b1a0f9e8d")


class InMemoryEvidenceSource:
    """Single-tenant stand-in for PostgresEvidenceSource (no ACLs: benchmark only)."""

    def __init__(self) -> None:
        self.chunks: dict[uuid.UUID, Evidence] = {}
        self.filenames: dict[uuid.UUID, str] = {}  # document_id -> file name
        self.headers_by_version: dict[uuid.UUID, str] = {}

    def add_file(
        self, path: Path, tokenizer: Tokenizer, max_tokens=512, overlap=64
    ) -> list[Evidence]:
        data = path.read_bytes()
        kind = validate_upload(path.name, data, len(data))
        parsed = parse_document(data, kind.parser)
        pieces = chunk_blocks(parsed.blocks, tokenizer, max_tokens=max_tokens, overlap=overlap)
        doc_id, version_id = uuid.uuid5(NS, path.name), uuid.uuid5(NS, f"{path.name}:v1")
        self.filenames[doc_id] = path.name
        out = []
        for c in pieces:
            ev = Evidence(
                chunk_id=uuid.uuid5(version_id, str(c.index)),
                document_id=doc_id,
                document_title=path.stem,
                version_id=version_id,
                version=1,
                effective_date=parsed.effective_date,
                section=c.section,
                page_start=c.page_start,
                page_end=c.page_end,
                content=c.content,
                score=0.0,
            )
            self.chunks[ev.chunk_id] = ev
            if c.index == 0:
                self.headers_by_version[version_id] = c.content
            out.append(ev)
        return out

    @property
    def document_ids(self) -> list[uuid.UUID]:
        return list(self.filenames)

    @property
    def version_ids(self) -> list[uuid.UUID]:
        return list({e.version_id for e in self.chunks.values()})

    async def authorize(self, candidate_ids: Sequence[uuid.UUID], scores, *, include_history):
        return [
            Evidence(**{**self.chunks[c].__dict__, "score": scores.get(c, 0.0)})
            for c in candidate_ids
            if c in self.chunks
        ]

    async def headers(self, version_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str]:
        return {v: self.headers_by_version[v] for v in version_ids if v in self.headers_by_version}
