"""Hybrid retrieval: dense + BM25 sparse candidates fused with RRF.

Every Qdrant query carries the mandatory tenant filter plus the allowed
document and current-version IDs computed from Postgres. Results are only
candidate IDs; text is loaded after the Postgres recheck (authorize.py).
"""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.retrieval.embeddings import Embedder
from app.retrieval.fusion import rrf_fuse
from app.retrieval.index import VectorIndex
from app.retrieval.sparse import bm25_query_vector

Mode = Literal["dense", "sparse", "hybrid"]


@dataclass(frozen=True)
class Candidate:
    chunk_id: UUID
    score: float
    dense_rank: int | None
    sparse_rank: int | None


class HybridRetriever:
    def __init__(
        self,
        index: VectorIndex,
        embedder: Embedder,
        *,
        dense_k: int = 20,
        sparse_k: int = 20,
        fused_k: int = 20,
        rrf_k: int = 60,
    ) -> None:
        self.index = index
        self.embedder = embedder
        self.dense_k, self.sparse_k, self.fused_k, self.rrf_k = dense_k, sparse_k, fused_k, rrf_k

    def retrieve(
        self,
        query: str,
        *,
        organization_id: UUID,
        document_ids: list[UUID],
        version_ids: list[UUID] | None = None,
        mode: Mode = "hybrid",
    ) -> list[Candidate]:
        if not document_ids:
            return []
        scope = {
            "organization_id": organization_id,
            "document_ids": document_ids,
            "version_ids": version_ids,
        }
        dense: list[UUID] = []
        sparse: list[UUID] = []
        if mode in ("dense", "hybrid"):
            vector = self.embedder.embed([query])[0]
            dense = [
                UUID(str(p.id))
                for p in self.index.search_dense(vector, limit=self.dense_k, **scope)
            ]
        if mode in ("sparse", "hybrid"):
            sv = bm25_query_vector(query)
            if sv.indices:
                sparse = [
                    UUID(str(p.id))
                    for p in self.index.search_sparse(sv, limit=self.sparse_k, **scope)
                ]
        rankings = [r for r in (dense, sparse) if r]
        fused = rrf_fuse(rankings, k=self.rrf_k, limit=self.fused_k)
        d_rank = {cid: i for i, cid in enumerate(dense, start=1)}
        s_rank = {cid: i for i, cid in enumerate(sparse, start=1)}
        return [Candidate(cid, score, d_rank.get(cid), s_rank.get(cid)) for cid, score in fused]
