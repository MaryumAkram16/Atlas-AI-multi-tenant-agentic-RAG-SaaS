# Answer benchmark: baseline vs agent (2026-11-25)

- Dataset: `evaluations/datasets/hr_refund_v1.jsonl` (26 answerable, 4 missing-evidence, 8 with stale sources)
- Corpus: `sample-data/acme` (38 chunks)
- Generator: extractive / extractive; embeddings: hash (1536 dims); tokenizer: simple
- Agent limits: 2 rewrites, 1 correction(s), 8 evidence chunks

| Metric | Baseline | Agent |
|---|---|---|
| Fact accuracy (answerable) | 0.769 | 0.808 |
| False abstention (answerable) | 0.077 | 0.077 |
| Correct abstention (missing evidence) | 0.750 | 1.000 |
| Evidence Recall@5 | 1.000 | 0.962 |
| Citation precision | 0.694 | 0.757 |
| Answers with ≥1 citation | 0.923 | 0.923 |
| Stale citation rate (conflict questions) | 1.000 | 0.000 |
| Avg retrieval attempts | 1.00 | 1.40 |
| Latency p50 (ms) | 6.1 | 18.8 |
| Latency p95 (ms) | 7.9 | 37.6 |

## How to read this

- **No real model.** Both systems used the offline extractive generator, which quotes source sentences. It cannot reason (e.g. say *yes* to the premium refund question) or paraphrase; this measures retrieval, routing, conflict handling, abstention and citation checks, not answer quality. Rerun with `--provider openai`.
- Offline hash embeddings: dense search is lexical, not semantic.
- Small corpus (38 chunks) and 30 hand-labeled, unreviewed questions: differences of one or two questions move rates by 4-25 points.
- Fact accuracy is a case-insensitive string match against `answer_facts`; it under-counts correct paraphrases.
- Latency is in-process (no network, no Postgres) on the machine that ran it.
