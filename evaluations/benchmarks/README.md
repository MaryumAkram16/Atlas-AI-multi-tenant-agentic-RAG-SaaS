# Benchmarks

## Retrieval: dense vs sparse vs hybrid

Needs Qdrant only (`docker compose up -d qdrant`). From `backend/`:

```bash
python -m app.evaluation.retrieval_benchmark --provider hash
```

```bash
OPENAI_API_KEY=... python -m app.evaluation.retrieval_benchmark --provider openai
```

The script indexes `sample-data/acme` into a throwaway collection with the
production parser, chunker, embeddings and tenant-filtered search, scores
`evaluations/datasets/hr_refund_v1.jsonl` (Recall@5, MRR, nDCG@10, latency
p50/p95 per mode and category) and writes `evaluations/reports/<date>-retrieval-<provider>.{md,json}`.

## Answers: baseline vs agent

```bash
python -m app.evaluation.answer_benchmark
```

```bash
OPENAI_API_KEY=... python -m app.evaluation.answer_benchmark --provider openai
```

Runs the Week 3 baseline and the LangGraph agent over the same index and
generator and reports fact accuracy (string match on `answer_facts`), false and
correct abstention, evidence Recall@5, citation precision, stale-citation rate
on conflict questions, retrieval attempts and latency.

Retrieval options: `--dimensions`, `--tokenizer tiktoken|simple`, `--dataset`, `--corpus`, `--out`, `--name`.
