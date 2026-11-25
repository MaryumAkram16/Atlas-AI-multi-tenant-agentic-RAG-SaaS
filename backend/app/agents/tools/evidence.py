"""Where the agent gets authorized evidence. Production rechecks every
candidate against Postgres under the caller's RLS identity."""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.agents.state import AuthContext
from app.db.session import UserDB
from app.retrieval.authorize import load_authorized_chunks, load_version_headers
from app.services.answering import Evidence


class EvidenceSource(Protocol):
    async def authorize(
        self, candidate_ids: Sequence[UUID], scores: dict[UUID, float], *, include_history: bool
    ) -> list[Evidence]: ...

    async def headers(self, version_ids: Sequence[UUID]) -> dict[UUID, str]: ...


class PostgresEvidenceSource:
    def __init__(self, db: UserDB, auth: AuthContext) -> None:
        self._db = db
        self._auth = auth

    async def authorize(
        self, candidate_ids: Sequence[UUID], scores: dict[UUID, float], *, include_history: bool
    ) -> list[Evidence]:
        async with self._db.transaction() as conn:
            return await load_authorized_chunks(
                conn,
                self._auth.organization_id,
                list(candidate_ids),
                list(self._auth.scope.document_ids),
                scores=scores,
                include_history=include_history,
            )

    async def headers(self, version_ids: Sequence[UUID]) -> dict[UUID, str]:
        async with self._db.transaction() as conn:
            return await load_version_headers(conn, self._auth.organization_id, version_ids)
