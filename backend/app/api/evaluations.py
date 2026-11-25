"""In-product evaluations (/v1/organizations/{org_id}/evaluation-datasets, /evaluations).

Owners and admins build datasets from their own documents and run the agent
against them. Postgres RLS enforces the same role rule and hides results
whose source documents the reader cannot access.
"""

import uuid
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from psycopg import errors

from app.auth.dependencies import DB, Org, OrgContext
from app.repositories import evaluations as repo
from app.schemas.evaluations import (
    CaseIn,
    CaseOut,
    CasesAdd,
    DatasetCreate,
    DatasetDetail,
    DatasetOut,
    ResultOut,
    RunCreate,
    RunDetail,
    RunOut,
)
from app.services import evaluations as service

router = APIRouter(prefix="/v1/organizations/{org_id}", tags=["evaluations"])


def _require_manager(ctx: OrgContext) -> None:
    if not ctx.is_manager:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="only owners and admins can manage evaluations"
        )


def _dataset_not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, detail="dataset not found")


async def _check_documents(conn, org_id: UUID, cases: list[CaseIn]) -> None:
    """Expected documents must be documents the caller can read in this org."""
    wanted = list({d for c in cases for d in c.expected_document_ids})
    if not wanted:
        return
    if set(wanted) - await repo.readable_document_ids(conn, org_id, wanted):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, detail="unknown expected document"
        )


async def _add_cases(conn, org_id: UUID, dataset_id: UUID, cases: list[CaseIn]) -> None:
    await _check_documents(conn, org_id, cases)
    await repo.insert_cases(conn, org_id, dataset_id, [c.model_dump() for c in cases])


# ---------------------------------------------------------------- datasets


@router.post("/evaluation-datasets", status_code=status.HTTP_201_CREATED)
async def create_dataset(body: DatasetCreate, ctx: Org, db: DB) -> DatasetDetail:
    _require_manager(ctx)
    dataset_id = uuid.uuid4()
    try:
        async with db.transaction() as conn:
            await repo.insert_dataset(
                conn,
                dataset_id=dataset_id,
                org_id=ctx.org_id,
                name=body.name,
                description=body.description,
                created_by=ctx.user.user_id,
            )
            await _add_cases(conn, ctx.org_id, dataset_id, body.cases)
            dataset = await repo.get_dataset(conn, ctx.org_id, dataset_id)
            cases = await repo.list_cases(conn, ctx.org_id, dataset_id)
    except errors.UniqueViolation:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="a dataset with this name already exists"
        ) from None
    return DatasetDetail(**dataset, cases=[CaseOut(**c) for c in cases])


@router.get("/evaluation-datasets")
async def list_datasets(ctx: Org, db: DB) -> list[DatasetOut]:
    _require_manager(ctx)
    async with db.transaction() as conn:
        rows = await repo.list_datasets(conn, ctx.org_id)
    return [DatasetOut(**r) for r in rows]


@router.get("/evaluation-datasets/{dataset_id}")
async def get_dataset(dataset_id: UUID, ctx: Org, db: DB) -> DatasetDetail:
    _require_manager(ctx)
    async with db.transaction() as conn:
        dataset = await repo.get_dataset(conn, ctx.org_id, dataset_id)
        if dataset is None:
            raise _dataset_not_found()
        cases = await repo.list_cases(conn, ctx.org_id, dataset_id)
    return DatasetDetail(**dataset, cases=[CaseOut(**c) for c in cases])


@router.post("/evaluation-datasets/{dataset_id}/cases", status_code=status.HTTP_201_CREATED)
async def add_cases(dataset_id: UUID, body: CasesAdd, ctx: Org, db: DB) -> DatasetDetail:
    _require_manager(ctx)
    async with db.transaction() as conn:
        if await repo.get_dataset(conn, ctx.org_id, dataset_id) is None:
            raise _dataset_not_found()
        await _add_cases(conn, ctx.org_id, dataset_id, body.cases)
        dataset = await repo.get_dataset(conn, ctx.org_id, dataset_id)
        cases = await repo.list_cases(conn, ctx.org_id, dataset_id)
    return DatasetDetail(**dataset, cases=[CaseOut(**c) for c in cases])


@router.delete(
    "/evaluation-datasets/{dataset_id}/cases/{case_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_case(dataset_id: UUID, case_id: UUID, ctx: Org, db: DB) -> Response:
    _require_manager(ctx)
    async with db.transaction() as conn:
        if not await repo.delete_case(conn, ctx.org_id, dataset_id, case_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="case not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/evaluation-datasets/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dataset(dataset_id: UUID, ctx: Org, db: DB) -> Response:
    """Past runs are kept (with the dataset name) for history."""
    _require_manager(ctx)
    async with db.transaction() as conn:
        if not await repo.delete_dataset(conn, ctx.org_id, dataset_id):
            raise _dataset_not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- runs


async def _run_detail(db, org_id: UUID, run_id: UUID) -> RunDetail:
    async with db.transaction() as conn:
        run = await repo.get_run(conn, org_id, run_id)
        if run is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="evaluation not found")
        results = await repo.list_results(conn, org_id, run_id)
    done = run["case_count"] if run["status"] == "succeeded" else len(results)
    return RunDetail(
        **run,
        results=[ResultOut(**r) for r in results],
        hidden_results=max(0, done - len(results)),
    )


@router.post("/evaluations", status_code=status.HTTP_201_CREATED)
async def run_evaluation(body: RunCreate, request: Request, ctx: Org, db: DB) -> RunDetail:
    """Run a dataset now with the full agent, as you (your readable documents)."""
    _require_manager(ctx)
    state = request.app.state
    try:
        run_id = await service.run_evaluation(
            db=db,
            ctx=ctx,
            dataset_id=body.dataset_id,
            retriever=state.retriever,
            llm=state.llm,
            settings=state.settings,
        )
    except service.DatasetNotFound:
        raise _dataset_not_found() from None
    return await _run_detail(db, ctx.org_id, run_id)


@router.get("/evaluations")
async def list_runs(
    ctx: Org, db: DB, limit: Annotated[int, Query(ge=1, le=100)] = 20
) -> list[RunOut]:
    _require_manager(ctx)
    async with db.transaction() as conn:
        rows = await repo.list_runs(conn, ctx.org_id, limit)
    return [RunOut(**r) for r in rows]


@router.get("/evaluations/{run_id}")
async def get_run(run_id: UUID, ctx: Org, db: DB) -> RunDetail:
    _require_manager(ctx)
    return await _run_detail(db, ctx.org_id, run_id)
