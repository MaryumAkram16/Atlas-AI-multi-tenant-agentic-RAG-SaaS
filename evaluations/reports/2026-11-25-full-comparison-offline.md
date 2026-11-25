# Full comparison: 2026-11-25

- Dataset: `evaluations/datasets/hr_refund_v1.jsonl`: 105 questions (88 answerable with facts, 16 with no evidence, 16 with stale sources, 8 injection checks)
- Corpus: `sample-data/acme` (80 chunks)
- Generator: extractive / extractive; embeddings: hash (1536 dims); tokenizer: simple

| Metric | dense | hybrid | hybrid+rerank | +rewrite | full agent |
|---|---|---|---|---|---|
| Fact accuracy (answerable) | 0.784 | 0.784 | 0.784 | 0.784 | 0.795 |
| False abstention (answerable) ↓ | 0.091 | 0.102 | 0.091 | 0.091 | 0.091 |
| Correct abstention (no evidence) | 0.688 | 0.688 | 0.688 | 0.875 | 0.875 |
| Evidence Recall@5 | 0.989 | 0.989 | 1.000 | 0.989 | 0.960 |
| Citation precision | 0.773 | 0.783 | 0.767 | 0.767 | 0.802 |
| Citation correctness | 0.950 | 0.962 | 0.950 | 0.950 | 0.938 |
| Faithfulness (proxy) | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| Stale citation rate ↓ | 0.938 | 0.938 | 0.938 | 0.938 | 0.000 |
| Injection resistance | 0.750 | 0.750 | 0.750 | 0.750 | 1.000 |
| Avg retrieval attempts | 1.00 | 1.00 | 1.00 | 1.33 | 1.35 |
| Latency p50 (ms) | 2.9 | 4.7 | 12.8 | 13.4 | 17.0 |
| Latency p95 (ms) | 3.4 | 6.3 | 19.1 | 29.8 | 32.9 |
| Tokens per question | 0 | 0 | 0 | 0 | 0 |

## How to read this

- **No real model.** Every configuration used the offline extractive generator, which quotes source sentences. It cannot reason or paraphrase, so this compares retrieval, routing, conflict handling, abstention, citation checks and injection handling, not answer quality. Token counts and cost are zero. Rerun with `--provider openai` for real numbers.
- Offline hash embeddings: dense search is lexical, not semantic.
- **Faithfulness (proxy)** uses the same deterministic checker as the full agent's citation verification, so it favours the full agent by construction. Use the LLM judge (real model runs) for an independent measure.
- Citation correctness: answered, answerable questions whose citations include at least one labeled-relevant chunk. Fact accuracy is a case-insensitive string match against `answer_facts` and under-counts correct paraphrases.
- Small corpus (80 chunks) and hand-written, unreviewed labels; small categories are anecdotal.
- Latency is in-process (no network, no Postgres) on the machine that ran it.
