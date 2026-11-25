"""Retrieval benchmark: dense-only vs sparse-only vs hybrid (RRF).

    python -m app.evaluation.retrieval_benchmark --provider hash
    python -m app.evaluation.retrieval_benchmark --provider openai   # needs OPENAI_API_KEY

Indexes the sample corpus into a throwaway Qdrant collection with the same
parsing, chunking, embeddings and filtered search the product uses, then
scores every labeled question. Needs only Qdrant (no Postgres, no LLM).
Relevance: a chunk is relevant when it comes from the labeled file and its
section path ends with the labeled heading.
"""

import argparse
import json
import statistics
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.config import Settings
from app.documents.validation import validate_upload
from app.evaluation.metrics import mrr, ndcg_at_k, percentile, recall_at_k
from app.ingestion.chunking import chunk_blocks
from app.ingestion.parsing import parse_document
from app.ingestion.tokenizer import get_tokenizer
from app.retrieval.embeddings import build_embedder
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.index import IndexPoint, VectorIndex
from app.retrieval.sparse import bm25_document_vector

REPO = Path(__file__).resolve().parents[3]
NS = uuid.UUID("1f0c9b7e-6a55-4d0e-9d8c-3c2b1a0f9e8d")
BENCH_ORG = uuid.uuid5(NS, "benchmark-org")
MODES = ("dense", "sparse", "hybrid")


@dataclass(frozen=True)
class IndexedChunk:
    id: uuid.UUID
    document: str
    section: str


def index_corpus(corpus: Path, index: VectorIndex, embedder, tokenizer, settings) -> dict:
    chunks: dict[uuid.UUID, IndexedChunk] = {}
    doc_ids, version_ids = [], []
    for path in sorted(corpus.glob("*")):
        if path.name.startswith(".") or path.is_dir():
            continue
        data = path.read_bytes()
        kind = validate_upload(path.name, data, len(data))
        parsed = parse_document(data, kind.parser)
        pieces = chunk_blocks(
            parsed.blocks,
            tokenizer,
            max_tokens=settings.chunk_tokens,
            overlap=settings.chunk_overlap_tokens,
        )
        doc_id, version_id = uuid.uuid5(NS, path.name), uuid.uuid5(NS, f"{path.name}:v1")
        doc_ids.append(doc_id)
        version_ids.append(version_id)
        texts = [f"{c.section}\n\n{c.content}" if c.section else c.content for c in pieces]
        vectors = embedder.embed(texts)
        points = []
        for c, text, vec in zip(pieces, texts, vectors, strict=True):
            cid = uuid.uuid5(version_id, str(c.index))
            chunks[cid] = IndexedChunk(cid, path.name, c.section or "")
            points.append(
                IndexPoint(
                    cid, vec, bm25_document_vector(text), BENCH_ORG, doc_id, version_id, c.index
                )
            )
        index.upsert(points)
    return {"chunks": chunks, "document_ids": doc_ids, "version_ids": version_ids}


def relevant_ids(question: dict, chunks: dict[uuid.UUID, IndexedChunk]) -> set[str]:
    out: set[str] = set()
    for label in question["relevant"]:
        hits = {
            str(c.id)
            for c in chunks.values()
            if c.document == label["document"] and c.section.endswith(label["section"])
        }
        if not hits:
            raise ValueError(f"{question['id']}: label matches no chunk: {label}")
        out |= hits
    return out


def run(settings: Settings, dataset: Path, corpus: Path, modes=MODES) -> dict:
    questions = [json.loads(line) for line in dataset.read_text().splitlines() if line.strip()]
    collection = f"atlas_bench_{uuid.uuid4().hex[:8]}"
    settings = settings.model_copy(update={"qdrant_collection": collection})
    index = VectorIndex.from_settings(settings)
    embedder = build_embedder(settings)
    tokenizer = get_tokenizer(settings.tokenizer)
    index.ensure_collection()
    try:
        corpus_info = index_corpus(corpus, index, embedder, tokenizer, settings)
        retriever = HybridRetriever(
            index,
            embedder,
            dense_k=settings.retrieval_dense_k,
            sparse_k=settings.retrieval_sparse_k,
            fused_k=settings.retrieval_fused_k,
            rrf_k=settings.rrf_k,
        )
        scored = [q for q in questions if q["relevant"]]
        labels = {q["id"]: relevant_ids(q, corpus_info["chunks"]) for q in scored}
        per_question: dict[str, list[dict]] = {m: [] for m in modes}
        for mode in modes:
            for q in scored:
                start = time.perf_counter()
                cands = retriever.retrieve(
                    q["question"],
                    organization_id=BENCH_ORG,
                    document_ids=corpus_info["document_ids"],
                    version_ids=corpus_info["version_ids"],
                    mode=mode,
                )
                latency = (time.perf_counter() - start) * 1000
                ranked = [str(c.chunk_id) for c in cands]
                rel = labels[q["id"]]
                per_question[mode].append(
                    {
                        "id": q["id"],
                        "category": q["category"],
                        "recall@5": recall_at_k(ranked, rel, 5),
                        "mrr": mrr(ranked, rel),
                        "ndcg@10": ndcg_at_k(ranked, rel, 10),
                        "latency_ms": latency,
                    }
                )
    finally:
        index.drop_collection()

    def summarize(rows: list[dict]) -> dict:
        lat = [r["latency_ms"] for r in rows]
        return {
            "n": len(rows),
            "recall@5": statistics.fmean(r["recall@5"] for r in rows),
            "mrr": statistics.fmean(r["mrr"] for r in rows),
            "ndcg@10": statistics.fmean(r["ndcg@10"] for r in rows),
            "latency_p50_ms": percentile(lat, 50),
            "latency_p95_ms": percentile(lat, 95),
        }

    by_category = {}
    for mode in modes:
        groups = defaultdict(list)
        for r in per_question[mode]:
            groups[r["category"]].append(r)
        by_category[mode] = {cat: summarize(rows) for cat, rows in sorted(groups.items())}

    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "dataset": str(dataset.relative_to(REPO)),
        "corpus": str(corpus.relative_to(REPO)),
        "questions_total": len(questions),
        "questions_scored": len(scored),
        "corpus_chunks": len(corpus_info["chunks"]),
        "config": {
            "embedding_provider": settings.embedding_provider,
            "embedding_model": settings.embedding_model
            if settings.embedding_provider == "openai"
            else "feature-hashing (offline)",
            "embedding_dimensions": settings.embedding_dimensions,
            "tokenizer": settings.tokenizer,
            "chunk_tokens": settings.chunk_tokens,
            "chunk_overlap_tokens": settings.chunk_overlap_tokens,
            "dense_k": settings.retrieval_dense_k,
            "sparse_k": settings.retrieval_sparse_k,
            "fused_k": settings.retrieval_fused_k,
            "rrf_k": settings.rrf_k,
        },
        "overall": {m: summarize(per_question[m]) for m in modes},
        "by_category": by_category,
        "per_question": per_question,
    }


def to_markdown(result: dict) -> str:
    cfg = result["config"]
    lines = [
        f"# Retrieval benchmark: {result['generated_at'][:10]}",
        "",
        f"- Dataset: `{result['dataset']}` ({result['questions_scored']} of "
        f"{result['questions_total']} questions scored; missing-evidence questions excluded)",
        f"- Corpus: `{result['corpus']}` ({result['corpus_chunks']} chunks)",
        f"- Embeddings: {cfg['embedding_provider']} / {cfg['embedding_model']} "
        f"({cfg['embedding_dimensions']} dims); tokenizer: {cfg['tokenizer']}",
        f"- Chunks {cfg['chunk_tokens']}/{cfg['chunk_overlap_tokens']} tokens; "
        f"dense k={cfg['dense_k']}, sparse k={cfg['sparse_k']}, RRF k={cfg['rrf_k']}, "
        f"fused top {cfg['fused_k']}",
        "",
        "## Overall",
        "",
        "| Mode | Recall@5 | MRR | nDCG@10 | p50 latency (ms) | p95 latency (ms) |",
        "|---|---|---|---|---|---|",
    ]
    for mode, s in result["overall"].items():
        lines.append(
            f"| {mode} | {s['recall@5']:.3f} | {s['mrr']:.3f} | {s['ndcg@10']:.3f} | "
            f"{s['latency_p50_ms']:.1f} | {s['latency_p95_ms']:.1f} |"
        )
    lines += [
        "",
        "## Recall@5 by category",
        "",
        "| Category | n | " + " | ".join(result["overall"]) + " |",
        "|---|---|" + "---|" * len(result["overall"]),
    ]
    cats = next(iter(result["by_category"].values()))
    for cat in cats:
        row = [f"{result['by_category'][m][cat]['recall@5']:.3f}" for m in result["overall"]]
        lines.append(f"| {cat} | {cats[cat]['n']} | " + " | ".join(row) + " |")
    lines += ["", "## How to read this", ""]
    if cfg["embedding_provider"] == "hash":
        lines.append(
            "- **Dense here is not semantic.** The offline hash embedder is feature-hashed "
            "bag-of-words, i.e. another lexical model. These numbers say nothing about "
            "`text-embedding-3-small`; rerun with `--provider openai` for that comparison."
        )
    if result["corpus_chunks"] < 200:
        share = 5 / result["corpus_chunks"]
        lines.append(
            f"- **Small corpus.** {result['corpus_chunks']} chunks, so the top 5 already covers "
            f"{share:.0%} of the corpus and Recall@5 saturates easily. MRR and nDCG separate "
            "the modes better; a larger corpus is needed before drawing conclusions."
        )
    if cfg["tokenizer"] != "tiktoken":
        lines.append(
            f"- Chunked with the `{cfg['tokenizer']}` tokenizer, not tiktoken; chunk "
            "boundaries may differ slightly from production."
        )
    lines += [
        "- Labels are hand-written and unreviewed; categories with n < 5 are anecdotal.",
        "- Latency covers query embedding plus Qdrant search on the machine that ran the "
        "benchmark; it excludes Postgres rechecks and generation.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--provider", choices=["hash", "openai"], default="hash")
    parser.add_argument("--dimensions", type=int, default=None)
    parser.add_argument("--tokenizer", choices=["tiktoken", "simple"], default=None)
    parser.add_argument(
        "--dataset", type=Path, default=REPO / "evaluations/datasets/hr_refund_v1.jsonl"
    )
    parser.add_argument("--corpus", type=Path, default=REPO / "sample-data/acme")
    parser.add_argument("--out", type=Path, default=REPO / "evaluations/reports")
    parser.add_argument("--name", default=None, help="report file stem")
    args = parser.parse_args()

    overrides = {"embedding_provider": args.provider}
    if args.dimensions:
        overrides["embedding_dimensions"] = args.dimensions
    if args.tokenizer:
        overrides["tokenizer"] = args.tokenizer
    settings = Settings().model_copy(update=overrides)
    result = run(settings, args.dataset.resolve(), args.corpus.resolve())
    args.out.mkdir(parents=True, exist_ok=True)
    stem = args.name or f"{result['generated_at'][:10]}-retrieval-{args.provider}"
    (args.out / f"{stem}.json").write_text(json.dumps(result, indent=2) + "\n")
    (args.out / f"{stem}.md").write_text(to_markdown(result))
    print(to_markdown(result))
    print(f"wrote {args.out / stem}.md and .json")


if __name__ == "__main__":
    main()
