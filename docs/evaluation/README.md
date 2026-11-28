# Evaluation

Two benchmarks over the 111-question dataset in
[`evaluations/datasets`](../../evaluations/datasets/README.md); how to run them is in
[`evaluations/benchmarks`](../../evaluations/benchmarks/README.md).

## Real-model results (Gemini)

Run on 2026-11-28 with `gemini-3.5-flash-lite` (generation and LLM judge) and
`gemini-embedding-001` (1536 dims), rule-based agent planning
(`AGENT_REASONER=heuristic`), the same 111 questions and 80-chunk corpus.

| Metric | hybrid | full agent (first run) | **full agent (after fixes)** |
|---|---|---|---|
| Fact accuracy (answerable) | 0.979 | 0.915 | **0.968** |
| False abstention (answerable) ↓ | 0.011 | 0.085 | **0.032** |
| Correct abstention (no evidence) | 1.000 | 1.000 | **1.000** |
| Evidence Recall@5 | 1.000 | 0.973 | 0.973 |
| Citation precision | 0.874 | 0.950 | 0.942 |
| Citation correctness | 0.989 | 1.000 | **1.000** |
| Faithfulness (LLM judge) | 0.975 | 1.000 | **1.000** |
| Stale citation rate ↓ | 0.812 | 0.000 | **0.000** |
| Injection resistance | 1.000 | 1.000 | 1.000 |
| Latency p50 / p95 (s) | 0.85 / 9.0 | 0.88 / 9.0 | 1.16 / 9.3 |
| Tokens per question | 2969 | 2411 | 2950 |

Reports: [first run](../../evaluations/reports/2026-11-28-gemini-hybrid-vs-agent.md),
[after fixes](../../evaluations/reports/2026-11-28-gemini-agent-fixed.md).

What the first run showed and what changed:

- **5 false abstentions came from the rule-based evidence check**, which needs the
  question's words in the passages ("minimum password length" vs "at least 14
  characters"). With `AGENT_WEAK_EVIDENCE=answer`, weak evidence after rewrites
  goes to the model, which abstains itself when the sources lack the answer.
  All 5 are now answered; correct abstention stayed at 100%.
- **3 "outdated handbook" questions are still declined.** The agent keeps the
  outdated handbook out of the citable sources (the precedence note now says
  what it stated), and the model declines because the current policy does not
  directly answer the question. The baseline answers them by quoting the
  outdated handbook as current.

Caveats: free-tier rate limits (500 requests per model per day, per-minute
limits) put waits into p95 latency, so latency here is not representative; the
judge is the same model family as the generator; the corpus and labels are
small and synthetic; fact accuracy is a string match.

## Offline results

All reports to date were produced **without a model key**: offline hash
embeddings, an extractive generator that quotes source sentences, and an
80-chunk synthetic corpus. They measure behaviour (retrieval, abstention,
conflict handling, citations, injection handling), not answer quality.

From [2026-11-25-full-comparison-offline](../../evaluations/reports/2026-11-25-full-comparison-offline.md):

| Metric | dense | hybrid | hybrid+rerank | +rewrite | full agent |
|---|---|---|---|---|---|
| Fact accuracy (answerable) | 0.777 | 0.787 | 0.787 | 0.777 | 0.787 |
| Correct abstention (no evidence) | 0.688 | 0.688 | 0.688 | 0.875 | 0.875 |
| Citation precision | 0.763 | 0.776 | 0.761 | 0.758 | 0.796 |
| Stale citation rate (lower is better) | 0.938 | 0.938 | 0.938 | 0.938 | 0.000 |
| Injection resistance | 0.750 | 0.750 | 0.750 | 0.750 | 1.000 |
| Latency p50 (ms, in-process) | 4.5 | 7.6 | 25.0 | 25.8 | 29.0 |

Six follow-up questions (q106-q111) carry the previous turn in `history`. The
agent rewrites them into standalone questions before searching; offline it answers
4 of 6 (the baselines get the history only in the prompt and answer 5 of 6, because
the extractive generator happens to quote the right sentence). A real-model run is
needed to judge follow-ups properly.

Caveats are listed in the report itself. Blueprint targets: Recall@5 ≥ 85%,
faithfulness ≥ 90% and citation correctness ≥ 95% are met in the Gemini run above;
p95 simple-query latency < 5 s has not been shown (free-tier rate limits).

## In-product evaluations

Owners and admins can also benchmark the agent on their **own** documents:
create a dataset (`POST /v1/organizations/{org}/evaluation-datasets`) with
questions and expected facts, documents or abstentions, then run it
(`POST /evaluations`). Runs use the full agent as the requesting user and
report fact accuracy, abstention accuracy, evidence hit rate, citation
precision, latency and tokens. Details: [ADR 0012](../decisions/0012-in-product-evaluations.md).

## Real-model run

```bash
cd backend && OPENAI_API_KEY=... python -m app.evaluation.answer_benchmark --provider openai
```

This also reports LLM-judge faithfulness and token cost (set
`LLM_INPUT_PRICE_PER_1M` / `LLM_OUTPUT_PRICE_PER_1M` for cost).
