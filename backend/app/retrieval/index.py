"""Qdrant index: one shared collection, named dense + BM25 sparse vectors,
and mandatory tenant filters on every query. Qdrant is only an index;
Postgres remains the authority (callers must recheck chunk IDs)."""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from qdrant_client import QdrantClient, models

from app.config import Settings
from app.retrieval.sparse import SparseVector

DENSE = "dense"
SPARSE = "bm25"


@dataclass(frozen=True)
class IndexPoint:
    id: UUID
    dense: list[float]
    sparse: SparseVector
    organization_id: UUID
    document_id: UUID
    version_id: UUID
    chunk_index: int


def _tenant_filter(
    organization_id: UUID | str,
    document_ids: Sequence[UUID | str] | None = None,
    version_id: UUID | str | None = None,
    version_ids: Sequence[UUID | str] | None = None,
) -> models.Filter:
    must: list[models.Condition] = [
        models.FieldCondition(
            key="organization_id", match=models.MatchValue(value=str(organization_id))
        )
    ]
    if document_ids is not None:
        must.append(
            models.FieldCondition(
                key="document_id", match=models.MatchAny(any=[str(d) for d in document_ids])
            )
        )
    if version_id is not None:
        must.append(
            models.FieldCondition(key="version_id", match=models.MatchValue(value=str(version_id)))
        )
    if version_ids is not None:
        must.append(
            models.FieldCondition(
                key="version_id", match=models.MatchAny(any=[str(v) for v in version_ids])
            )
        )
    return models.Filter(must=must)


class VectorIndex:
    def __init__(self, client: QdrantClient, collection: str, dimensions: int) -> None:
        self._client = client
        self.collection = collection
        self.dimensions = dimensions

    @classmethod
    def from_settings(cls, settings: Settings) -> "VectorIndex":
        client = QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None,
            timeout=30,
            # Don't contact the server at construction; /ready reports reachability.
            check_compatibility=False,
        )
        return cls(client, settings.qdrant_collection, settings.embedding_dimensions)

    def ensure_collection(self) -> None:
        if self._client.collection_exists(self.collection):
            return
        self._client.create_collection(
            self.collection,
            vectors_config={
                DENSE: models.VectorParams(size=self.dimensions, distance=models.Distance.COSINE)
            },
            sparse_vectors_config={SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)},
        )
        self._client.create_payload_index(
            self.collection,
            "organization_id",
            models.KeywordIndexParams(type=models.KeywordIndexType.KEYWORD, is_tenant=True),
        )
        for field in ("document_id", "version_id"):
            self._client.create_payload_index(
                self.collection, field, models.PayloadSchemaType.KEYWORD
            )

    def drop_collection(self) -> None:
        if self._client.collection_exists(self.collection):
            self._client.delete_collection(self.collection)

    def upsert(self, points: list[IndexPoint]) -> None:
        if not points:
            return
        self._client.upsert(
            self.collection,
            points=[
                models.PointStruct(
                    id=str(p.id),
                    vector={
                        DENSE: p.dense,
                        SPARSE: models.SparseVector(
                            indices=p.sparse.indices, values=p.sparse.values
                        ),
                    },
                    # IDs only: no document text is stored in the index.
                    payload={
                        "organization_id": str(p.organization_id),
                        "document_id": str(p.document_id),
                        "version_id": str(p.version_id),
                        "chunk_id": str(p.id),
                        "chunk_index": p.chunk_index,
                    },
                )
                for p in points
            ],
            wait=True,
        )

    def count(
        self,
        *,
        organization_id: UUID | str,
        document_id: UUID | str | None = None,
        version_id: UUID | str | None = None,
    ) -> int:
        flt = _tenant_filter(organization_id, [document_id] if document_id else None, version_id)
        return self._client.count(self.collection, count_filter=flt, exact=True).count

    def delete_version(self, *, organization_id: UUID | str, version_id: UUID | str) -> None:
        self._client.delete(
            self.collection,
            points_selector=models.FilterSelector(
                filter=_tenant_filter(organization_id, version_id=version_id)
            ),
            wait=True,
        )

    def delete_points(self, ids: list[UUID]) -> None:
        self._client.delete(
            self.collection,
            points_selector=models.PointIdsList(points=[str(i) for i in ids]),
            wait=True,
        )

    def delete_document(self, *, organization_id: UUID | str, document_id: UUID | str) -> None:
        self._client.delete(
            self.collection,
            points_selector=models.FilterSelector(
                filter=_tenant_filter(organization_id, [document_id])
            ),
            wait=True,
        )

    # Search requires both the tenant and an explicit list of allowed documents.
    def search_dense(
        self,
        vector: list[float],
        *,
        organization_id: UUID | str,
        document_ids: Sequence[UUID | str],
        limit: int,
        version_ids: Sequence[UUID | str] | None = None,
    ) -> list[models.ScoredPoint]:
        return self._query(DENSE, vector, organization_id, document_ids, version_ids, limit)

    def search_sparse(
        self,
        vector: SparseVector,
        *,
        organization_id: UUID | str,
        document_ids: Sequence[UUID | str],
        limit: int,
        version_ids: Sequence[UUID | str] | None = None,
    ) -> list[models.ScoredPoint]:
        query = models.SparseVector(indices=vector.indices, values=vector.values)
        return self._query(SPARSE, query, organization_id, document_ids, version_ids, limit)

    def _query(self, using, query, organization_id, document_ids, version_ids, limit):
        if not document_ids:
            return []
        flt = _tenant_filter(organization_id, document_ids, version_ids=version_ids)
        return self._client.query_points(
            self.collection,
            query=query,
            using=using,
            query_filter=flt,
            limit=limit,
            with_payload=True,
        ).points
