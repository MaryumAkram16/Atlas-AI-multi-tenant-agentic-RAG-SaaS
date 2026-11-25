"""In-product evaluation runs.

A run answers every case of a dataset with the full agent, as the requesting
user (their own AuthContext and readable documents), then scores each answer:
expected facts present, abstention when expected, expected documents cited.
Runs are synchronous and capped (`evaluation_max_cases`); each case counts as
one question for quotas and usage.
"""

import logging
import statistics
import time
import uuid
from typing import Any
from uuid import UUID

from app.agents.graph import run_agent
from app.agents.state import AgentDeps, AuthContext
from app.agents.tools.evidence import PostgresEvidenceSource
from app.api.errors import ApiError
from app.auth.dependencies import OrgContext
from app.config import Settings
from app.db.session import UserDB
from app.repositories import chat as chat_repo
from app.repositories import evaluations as repo
from app.retrieval.authorize import allowed_documents
from app.retrieval.hybrid import HybridRetriever
from app.services import limits
from app.services.answering import parse_citations
from app.services.chat import _cost, _total_usage, build_reasoner
from app.services.llm import ChatLLM

logger = logging.getLogger(__name__)


class DatasetNotFound(Exception):
    pass


def score(case: dict, status: str, answer: str, cited: list[UUID]) -> dict[str, Any]:
    abstained = status != "answered"
    facts = case["expected_facts"]
    expected_docs = set(case["expected_document_ids"])
    lowered = answer.lower()
    return {
        "abstained": abstained,
        "fact_hit": (not abstained and all(f.lower() in lowered for f in facts)) if facts else None,
        "abstention_correct": abstained if case["should_abstain"] else None,
        "evidence_hit": bool(expected_docs & set(cited))
        if expected_docs and not case["should_abstain"]
        else None,
    }


def _rate(values: list[bool]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def _percentile(values: list[int], q: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def summarize(rows: list[dict], expected: dict[UUID, set[UUID]]) -> dict[str, Any]:
    with_facts = [r for r in rows if r["fact_hit"] is not None]
    precisions = [
        len(set(r["cited_document_ids"]) & expected[r["case_id"]]) / len(r["cited_document_ids"])
        for r in rows
        if r["cited_document_ids"] and expected.get(r["case_id"])
    ]
    latencies = [r["latency_ms"] for r in rows]
    costs = [r["estimated_cost"] for r in rows if r["estimated_cost"] is not None]
    return {
        "cases": len(rows),
        "answered_rate": _rate([not r["abstained"] for r in rows]),
        "fact_accuracy": _rate([r["fact_hit"] for r in with_facts]),
        "false_abstention": _rate([r["abstained"] for r in with_facts]),
        "abstention_accuracy": _rate(
            [r["abstention_correct"] for r in rows if r["abstention_correct"] is not None]
        ),
        "evidence_hit_rate": _rate(
            [r["evidence_hit"] for r in rows if r["evidence_hit"] is not None]
        ),
        "citation_precision": round(statistics.mean(precisions), 3) if precisions else None,
        "latency_p50_ms": _percentile(latencies, 0.5),
        "latency_p95_ms": _percentile(latencies, 0.95),
        "prompt_tokens": sum(r["prompt_tokens"] for r in rows),
        "completion_tokens": sum(r["completion_tokens"] for r in rows),
        "estimated_cost": float(round(sum(costs), 6)) if costs else None,
    }


def run_config(settings: Settings, llm: ChatLLM) -> dict[str, Any]:
    return {
        "pipeline": "full agent",
        "model": llm.name,
        "llm_provider": settings.llm_provider,
        "embedding_provider": settings.embedding_provider,
        "rewrite": settings.agent_enable_rewrite,
        "conflicts": settings.agent_enable_conflicts,
        "verification": settings.agent_enable_verification,
        "injection_filter": settings.agent_enable_injection_filter,
    }


async def _answer(question: str, auth: AuthContext, db, retriever, llm, settings):
    async def emit(kind: str, data: dict) -> None:  # progress is not streamed here
        return None

    reasoner = build_reasoner(settings, llm)
    deps = AgentDeps(
        auth=auth,
        evidence=PostgresEvidenceSource(db, auth),
        retriever=retriever,
        llm=llm,
        reasoner=reasoner,
        settings=settings,
        emit=emit,
        deadline=time.monotonic() + settings.agent_timeout_seconds,
    )
    try:
        state, _ = await run_agent(question, [], deps)
    except Exception as exc:  # one failing case must not abort the run
        logger.warning("evaluation case failed: %s", type(exc).__name__)
        state = {"status": "error", "answer": ""}
    usage = _total_usage(llm.name, [*state.get("usage", []), *getattr(reasoner, "usage", [])])
    return state, usage


async def run_evaluation(
    *,
    db: UserDB,
    ctx: OrgContext,
    dataset_id: UUID,
    retriever: HybridRetriever,
    llm: ChatLLM,
    settings: Settings,
) -> UUID:
    org, user_id = ctx.org_id, ctx.user.user_id
    run_id = uuid.uuid4()
    async with db.transaction() as conn:
        await limits.rate_limit(
            conn,
            org,
            "evaluation",
            settings.rate_limit_evaluation,
            settings.rate_limit_window_seconds,
        )
        dataset = await repo.get_dataset(conn, org, dataset_id)
        if dataset is None:
            raise DatasetNotFound()
        cases = await repo.list_cases(conn, org, dataset_id)
        if not cases:
            raise ApiError(409, "empty_dataset", "Add cases to the dataset before running it.")
        if len(cases) > settings.evaluation_max_cases:
            raise ApiError(
                422,
                "too_many_cases",
                f"A run is limited to {settings.evaluation_max_cases} cases.",
            )
        await limits.check_question(conn, settings, org, count=len(cases))
        scope = await allowed_documents(conn, org, None)
        await repo.insert_run(
            conn,
            run_id=run_id,
            org_id=org,
            dataset=dataset,
            config=run_config(settings, llm),
            case_count=len(cases),
            created_by=user_id,
        )

    auth = AuthContext(organization_id=org, user_id=user_id, role=ctx.role, scope=scope)
    rows: list[dict] = []
    try:
        for position, case in enumerate(cases, start=1):
            started = time.perf_counter()
            state, usage = await _answer(case["question"], auth, db, retriever, llm, settings)
            status = state.get("status") or "error"
            answer = state.get("answer") or ""
            evidence = state.get("answer_evidence") or []
            cited_numbers = parse_citations(answer, len(evidence)) if status == "answered" else []
            cited = list(dict.fromkeys(evidence[n - 1].document_id for n in cited_numbers))
            row = {
                "case_id": case["id"],
                "position": position,
                "question": case["question"],
                "status": status,
                "answer": answer,
                **score(case, status, answer, cited),
                "cited_document_ids": cited,
                "source_document_ids": sorted({e.document_id for e in evidence}),
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "prompt_tokens": usage.prompt_tokens if usage else 0,
                "completion_tokens": usage.completion_tokens if usage else 0,
                "estimated_cost": _cost(settings, usage),
            }
            async with db.transaction() as conn:
                await repo.insert_result(conn, org, run_id, row)
                await chat_repo.insert_usage(
                    conn,
                    org_id=org,
                    user_id=user_id,
                    message_id=None,
                    model=usage.model if usage else llm.name,
                    prompt_tokens=row["prompt_tokens"],
                    completion_tokens=row["completion_tokens"],
                    estimated_cost=row["estimated_cost"],
                )
            rows.append(row)
        expected = {c["id"]: set(c["expected_document_ids"]) for c in cases}
        metrics = summarize(rows, expected)
        async with db.transaction() as conn:
            await repo.finish_run(conn, run_id, status="succeeded", metrics=metrics, error=None)
    except Exception as exc:
        logger.warning("evaluation run failed: %s run_id=%s", type(exc).__name__, run_id)
        async with db.transaction() as conn:
            await repo.finish_run(
                conn,
                run_id,
                status="failed",
                metrics=None,
                error="The run stopped before finishing. Completed cases are kept.",
            )
    logger.info("evaluation run finished run_id=%s cases=%s", run_id, len(rows))
    return run_id
