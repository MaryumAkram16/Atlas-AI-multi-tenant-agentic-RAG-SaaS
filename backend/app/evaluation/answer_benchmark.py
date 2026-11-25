"""Answer benchmark: Week 3 baseline pipeline vs the LangGraph agent.

    python -m app.evaluation.answer_benchmark                       # offline
    python -m app.evaluation.answer_benchmark --provider openai     # real embeddings + LLM

Both systems use the same corpus, Qdrant index (tenant-filtered search) and
generator. Postgres is replaced by an in-memory evidence source (single
tenant), so this measures answer behaviour, not access control.
"""

import argparse
import asyncio
import json
import statistics
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.agents.graph import run_agent
from app.agents.state import AgentDeps, AuthContext
from app.config import Settings
from app.evaluation.memory import InMemoryEvidenceSource
from app.evaluation.metrics import percentile, recall_at_k
from app.evaluation.retrieval_benchmark import IndexedChunk, relevant_ids
from app.ingestion.tokenizer import get_tokenizer
from app.retrieval.authorize import SearchScope
from app.retrieval.embeddings import build_embedder
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.index import IndexPoint, VectorIndex
from app.retrieval.sparse import bm25_document_vector
from app.services.answering import parse_citations
from app.services.baseline import baseline_answer
from app.services.chat import build_reasoner
from app.services.llm import build_llm

REPO = Path(__file__).resolve().parents[3]
ORG = uuid.uuid5(uuid.NAMESPACE_DNS, "atlas-benchmark-org")
SYSTEMS = ("baseline", "agent")


def _index(source: InMemoryEvidenceSource, index: VectorIndex, embedder) -> None:
    chunks = list(source.chunks.values())
    texts = [f"{c.section}\n\n{c.content}" if c.section else c.content for c in chunks]
    vectors = embedder.embed(texts)
    index.upsert(
        [
            IndexPoint(c.chunk_id, v, bm25_document_vector(t), ORG, c.document_id, c.version_id, i)
            for i, (c, t, v) in enumerate(zip(chunks, texts, vectors, strict=True))
        ]
    )


async def _run_system(system, q, *, source, retriever, llm, settings):
    started = time.perf_counter()
    if system == "baseline":
        r = await baseline_answer(
            q["question"],
            organization_id=ORG,
            document_ids=source.document_ids,
            version_ids=source.version_ids,
            retriever=retriever,
            evidence_source=source,
            llm=llm,
            max_chunks=settings.answer_max_chunks,
        )
        answer, status, evidence, cited, attempts = r.answer, r.status, r.evidence, r.cited, 1
    else:

        async def emit(kind, data):
            return None

        scope = SearchScope(
            tuple(source.document_ids), tuple(source.version_ids), tuple(source.version_ids)
        )
        deps = AgentDeps(
            auth=AuthContext(ORG, uuid.uuid4(), "member", scope),
            evidence=source,
            retriever=retriever,
            llm=llm,
            reasoner=build_reasoner(settings, llm),
            settings=settings,
            emit=emit,
            deadline=time.monotonic() + settings.agent_timeout_seconds,
        )
        state, _ = await run_agent(q["question"], [], deps)
        answer, status = state.get("answer", ""), state.get("status", "error")
        evidence = state.get("answer_evidence") or state.get("evidence") or []
        cited = (
            [evidence[n - 1] for n in parse_citations(answer, len(evidence))]
            if status == "answered"
            else []
        )
        attempts = state.get("attempts", 0)
    return {
        "answer": answer,
        "status": status,
        "evidence": evidence,
        "cited": cited,
        "attempts": attempts,
        "latency_ms": (time.perf_counter() - started) * 1000,
    }


def _score(q, out, labels, filenames):
    abstained = out["status"] != "answered"
    row = {
        "id": q["id"],
        "category": q["category"],
        "status": out["status"],
        "abstained": abstained,
        "attempts": out["attempts"],
        "latency_ms": out["latency_ms"],
    }
    cited_files = {filenames[e.document_id] for e in out["cited"]}
    if q["relevant"]:
        rel = labels[q["id"]]
        evidence_ids = [str(e.chunk_id) for e in out["evidence"]]
        row["evidence_recall@5"] = recall_at_k(evidence_ids, rel, 5)
        row["fact_hit"] = (not abstained) and all(
            f.lower() in out["answer"].lower() for f in q["answer_facts"]
        )
        if out["cited"]:
            row["citation_precision"] = sum(str(e.chunk_id) in rel for e in out["cited"]) / len(
                out["cited"]
            )
    if q["stale_documents"]:
        row["stale_cited"] = bool(cited_files & set(q["stale_documents"]))
    return row


def _summary(rows):
    answerable = [r for r in rows if "fact_hit" in r]
    missing = [r for r in rows if r["category"] == "missing_evidence"]
    stale = [r for r in rows if "stale_cited" in r]
    cited = [r["citation_precision"] for r in answerable if "citation_precision" in r]
    lat = [r["latency_ms"] for r in rows]

    def mean(xs):
        return statistics.fmean(xs) if xs else 0.0

    return {
        "fact_accuracy": mean([r["fact_hit"] for r in answerable]),
        "false_abstention_rate": mean([r["abstained"] for r in answerable]),
        "correct_abstention_rate": mean([r["abstained"] for r in missing]),
        "evidence_recall@5": mean([r["evidence_recall@5"] for r in answerable]),
        "citation_precision": mean(cited),
        "answers_with_citations": len(cited) / len(answerable) if answerable else 0.0,
        "stale_citation_rate": mean([r["stale_cited"] for r in stale]),
        "avg_retrieval_attempts": mean([r["attempts"] for r in rows]),
        "latency_p50_ms": percentile(lat, 50),
        "latency_p95_ms": percentile(lat, 95),
        "n_answerable": len(answerable),
        "n_missing": len(missing),
        "n_stale": len(stale),
    }


def _load(settings: Settings, dataset: Path, corpus: Path):
    questions = [json.loads(x) for x in dataset.read_text().splitlines() if x.strip()]
    tokenizer = get_tokenizer(settings.tokenizer)
    source = InMemoryEvidenceSource()
    for path in sorted(corpus.glob("*")):
        if path.is_file() and not path.name.startswith("."):
            source.add_file(path, tokenizer, settings.chunk_tokens, settings.chunk_overlap_tokens)
    return questions, source


async def run(settings: Settings, dataset: Path, corpus: Path) -> dict:
    collection = f"atlas_bench_{uuid.uuid4().hex[:8]}"
    settings = settings.model_copy(update={"qdrant_collection": collection})
    questions, source = _load(settings, dataset, corpus)
    chunks = {
        c.chunk_id: IndexedChunk(c.chunk_id, source.filenames[c.document_id], c.section or "")
        for c in source.chunks.values()
    }
    labels = {q["id"]: relevant_ids(q, chunks) for q in questions if q["relevant"]}
    index = VectorIndex.from_settings(settings)
    embedder = build_embedder(settings)
    llm = build_llm(settings)
    index.ensure_collection()
    try:
        _index(source, index, embedder)
        index.wait_until_green()
        retriever = HybridRetriever(
            index,
            embedder,
            dense_k=settings.retrieval_dense_k,
            sparse_k=settings.retrieval_sparse_k,
            fused_k=settings.retrieval_fused_k,
            rrf_k=settings.rrf_k,
        )
        rows = {s: [] for s in SYSTEMS}
        for system in SYSTEMS:
            for q in questions:
                out = await _run_system(
                    system, q, source=source, retriever=retriever, llm=llm, settings=settings
                )
                rows[system].append(_score(q, out, labels, source.filenames))
    finally:
        index.drop_collection()
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "dataset": str(dataset.relative_to(REPO)),
        "corpus": str(corpus.relative_to(REPO)),
        "corpus_chunks": len(source.chunks),
        "config": {
            "embedding_provider": settings.embedding_provider,
            "embedding_dimensions": settings.embedding_dimensions,
            "llm_provider": settings.llm_provider,
            "llm_model": settings.llm_model if settings.llm_provider == "openai" else "extractive",
            "tokenizer": settings.tokenizer,
            "agent_max_rewrites": settings.agent_max_rewrites,
            "agent_max_corrections": settings.agent_max_corrections,
            "answer_max_chunks": settings.answer_max_chunks,
        },
        "summary": {s: _summary(rows[s]) for s in SYSTEMS},
        "per_question": rows,
    }


METRICS = [
    ("fact_accuracy", "Fact accuracy (answerable)", True),
    ("false_abstention_rate", "False abstention (answerable)", False),
    ("correct_abstention_rate", "Correct abstention (missing evidence)", True),
    ("evidence_recall@5", "Evidence Recall@5", True),
    ("citation_precision", "Citation precision", True),
    ("answers_with_citations", "Answers with ≥1 citation", True),
    ("stale_citation_rate", "Stale citation rate (conflict questions)", False),
    ("avg_retrieval_attempts", "Avg retrieval attempts", None),
    ("latency_p50_ms", "Latency p50 (ms)", None),
    ("latency_p95_ms", "Latency p95 (ms)", None),
]


def to_markdown(result: dict) -> str:
    cfg, s = result["config"], result["summary"]
    b, a = s["baseline"], s["agent"]
    lines = [
        f"# Answer benchmark: baseline vs agent ({result['generated_at'][:10]})",
        "",
        f"- Dataset: `{result['dataset']}` ({b['n_answerable']} answerable, {b['n_missing']} "
        f"missing-evidence, {b['n_stale']} with stale sources)",
        f"- Corpus: `{result['corpus']}` ({result['corpus_chunks']} chunks)",
        f"- Generator: {cfg['llm_provider']} / {cfg['llm_model']}; embeddings: "
        f"{cfg['embedding_provider']} ({cfg['embedding_dimensions']} dims); tokenizer: "
        f"{cfg['tokenizer']}",
        f"- Agent limits: {cfg['agent_max_rewrites']} rewrites, {cfg['agent_max_corrections']} "
        f"correction(s), {cfg['answer_max_chunks']} evidence chunks",
        "",
        "| Metric | Baseline | Agent |",
        "|---|---|---|",
    ]
    for key, label, _ in METRICS:
        fmt = "{:.1f}" if "latency" in key else "{:.2f}" if "attempts" in key else "{:.3f}"
        lines.append(f"| {label} | {fmt.format(b[key])} | {fmt.format(a[key])} |")
    lines += ["", "## How to read this", ""]
    if cfg["llm_provider"] == "extractive":
        lines.append(
            "- **No real model.** Both systems used the offline extractive generator, which "
            "quotes source sentences. It cannot reason (e.g. say *yes* to the premium refund "
            "question) or paraphrase; this measures retrieval, routing, conflict handling, "
            "abstention and citation checks, not answer quality. Rerun with `--provider openai`."
        )
    if cfg["embedding_provider"] == "hash":
        lines.append("- Offline hash embeddings: dense search is lexical, not semantic.")
    lines += [
        f"- Small corpus ({result['corpus_chunks']} chunks) and 30 hand-labeled, unreviewed "
        "questions: differences of one or two questions move rates by 4-25 points.",
        "- Fact accuracy is a case-insensitive string match against `answer_facts`; it "
        "under-counts correct paraphrases.",
        "- Latency is in-process (no network, no Postgres) on the machine that ran it.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--provider", choices=["offline", "openai"], default="offline")
    parser.add_argument("--tokenizer", choices=["tiktoken", "simple"], default=None)
    parser.add_argument(
        "--dataset", type=Path, default=REPO / "evaluations/datasets/hr_refund_v1.jsonl"
    )
    parser.add_argument("--corpus", type=Path, default=REPO / "sample-data/acme")
    parser.add_argument("--out", type=Path, default=REPO / "evaluations/reports")
    parser.add_argument("--name", default=None)
    args = parser.parse_args()
    updates = (
        {"embedding_provider": "openai", "llm_provider": "openai"}
        if args.provider == "openai"
        else {"embedding_provider": "hash", "llm_provider": "extractive"}
    )
    if args.tokenizer:
        updates["tokenizer"] = args.tokenizer
    settings = Settings().model_copy(update=updates)
    result = asyncio.run(run(settings, args.dataset.resolve(), args.corpus.resolve()))
    args.out.mkdir(parents=True, exist_ok=True)
    stem = args.name or f"{result['generated_at'][:10]}-answers-{args.provider}"
    (args.out / f"{stem}.json").write_text(json.dumps(result, indent=2, default=str) + "\n")
    (args.out / f"{stem}.md").write_text(to_markdown(result))
    print(to_markdown(result))
    print(f"wrote {args.out / stem}.md and .json")


if __name__ == "__main__":
    main()
