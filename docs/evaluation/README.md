# Evaluation

Two benchmarks over the 105-question dataset in
[`evaluations/datasets`](../../evaluations/datasets/README.md); how to run them is in
[`evaluations/benchmarks`](../../evaluations/benchmarks/README.md).

## Results so far (offline only)

All reports to date were produced **without a model key**: offline hash
embeddings, an extractive generator that quotes source sentences, and an
80-chunk synthetic corpus. They measure behaviour (retrieval, abstention,
conflict handling, citations, injection handling), not answer quality.

From [2026-11-25-full-comparison-offline](../../evaluations/reports/2026-11-25-full-comparison-offline.md):

| Metric | dense | hybrid | hybrid+rerank | +rewrite | full agent |
|---|---|---|---|---|---|
| Fact accuracy (answerable) | 0.784 | 0.784 | 0.784 | 0.784 | 0.795 |
| Correct abstention (no evidence) | 0.688 | 0.688 | 0.688 | 0.875 | 0.875 |
| Citation precision | 0.773 | 0.783 | 0.767 | 0.767 | 0.802 |
| Stale citation rate (lower is better) | 0.938 | 0.938 | 0.938 | 0.938 | 0.000 |
| Injection resistance | 0.750 | 0.750 | 0.750 | 0.750 | 1.000 |
| Latency p50 (ms, in-process) | 2.9 | 4.7 | 12.8 | 13.4 | 17.0 |

Caveats are listed in the report itself. Blueprint targets (Recall@5 ≥ 85%,
faithfulness ≥ 90%, citation correctness ≥ 95%, p95 simple-query latency < 5 s)
are **targets**; they have not been measured with a real model yet.

## Real-model run

```bash
cd backend && OPENAI_API_KEY=... python -m app.evaluation.answer_benchmark --provider openai
```

This also reports LLM-judge faithfulness and token cost (set
`LLM_INPUT_PRICE_PER_1M` / `LLM_OUTPUT_PRICE_PER_1M` for cost).
