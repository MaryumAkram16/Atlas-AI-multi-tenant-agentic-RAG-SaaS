# Evaluation

Two benchmarks over the 111-question dataset in
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
| Fact accuracy (answerable) | 0.777 | 0.787 | 0.787 | 0.777 | 0.787 |
| Correct abstention (no evidence) | 0.688 | 0.688 | 0.688 | 0.875 | 0.875 |
| Citation precision | 0.763 | 0.776 | 0.761 | 0.758 | 0.798 |
| Stale citation rate (lower is better) | 0.938 | 0.938 | 0.938 | 0.938 | 0.000 |
| Injection resistance | 0.750 | 0.750 | 0.750 | 0.750 | 1.000 |
| Latency p50 (ms, in-process) | 2.7 | 4.1 | 11.9 | 11.9 | 13.5 |

Six follow-up questions (q106-q111) carry the previous turn in `history`. The
agent rewrites them into standalone questions before searching; offline it answers
4 of 6 (the baselines get the history only in the prompt and answer 5 of 6, because
the extractive generator happens to quote the right sentence). A real-model run is
needed to judge follow-ups properly.

Caveats are listed in the report itself. Blueprint targets (Recall@5 ≥ 85%,
faithfulness ≥ 90%, citation correctness ≥ 95%, p95 simple-query latency < 5 s)
are **targets**; they have not been measured with a real model yet.

## Real-model run

```bash
cd backend && OPENAI_API_KEY=... python -m app.evaluation.answer_benchmark --provider openai
```

This also reports LLM-judge faithfulness and token cost (set
`LLM_INPUT_PRICE_PER_1M` / `LLM_OUTPUT_PRICE_PER_1M` for cost).
