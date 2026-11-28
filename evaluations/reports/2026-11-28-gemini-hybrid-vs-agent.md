# Full comparison: 2026-11-28

- Dataset: `evaluations/datasets/hr_refund_v1.jsonl`: 111 questions (94 answerable with facts, 16 with no evidence, 16 with stale sources, 8 injection checks)
- Corpus: `sample-data/acme` (80 chunks)
- Generator: openai / gemini-3.5-flash-lite; embeddings: openai (1536 dims); tokenizer: simple

| Metric | hybrid | full agent |
|---|---|---|
| Fact accuracy (answerable) | 0.979 | 0.915 |
| False abstention (answerable) ↓ | 0.011 | 0.085 |
| Correct abstention (no evidence) | 1.000 | 1.000 |
| Evidence Recall@5 | 1.000 | 0.973 |
| Citation precision | 0.874 | 0.950 |
| Citation correctness | 0.989 | 1.000 |
| Faithfulness (proxy) | 0.948 | 1.000 |
| Faithfulness (LLM judge) | 0.975 | 1.000 |
| Stale citation rate ↓ | 0.812 | 0.000 |
| Injection resistance | 1.000 | 1.000 |
| Avg retrieval attempts | 1.00 | 1.35 |
| Latency p50 (ms) | 852.2 | 881.3 |
| Latency p95 (ms) | 9034.1 | 9011.0 |
| Tokens per question | 2969 | 2411 |

## How to read this

- **Faithfulness (proxy)** uses the same deterministic checker as the full agent's citation verification, so it favours the full agent by construction. Use the LLM judge (real model runs) for an independent measure.
- Citation correctness: answered, answerable questions whose citations include at least one labeled-relevant chunk. Fact accuracy is a case-insensitive string match against `answer_facts` and under-counts correct paraphrases.
- Small corpus (80 chunks) and hand-written, unreviewed labels; small categories are anecdotal.
- Latency is in-process (no network, no Postgres) on the machine that ran it.
