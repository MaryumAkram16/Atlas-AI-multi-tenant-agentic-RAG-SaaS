# Retrieval benchmark: 2026-11-25

- Dataset: `evaluations/datasets/hr_refund_v1.jsonl` (26 of 30 questions scored; missing-evidence questions excluded)
- Corpus: `sample-data/acme` (38 chunks)
- Embeddings: hash / feature-hashing (offline) (1536 dims); tokenizer: simple
- Chunks 512/64 tokens; dense k=20, sparse k=20, RRF k=60, fused top 20

## Overall

| Mode | Recall@5 | MRR | nDCG@10 | p50 latency (ms) | p95 latency (ms) |
|---|---|---|---|---|---|
| dense | 1.000 | 0.879 | 0.905 | 2.3 | 2.9 |
| sparse | 0.968 | 0.840 | 0.868 | 1.7 | 2.3 |
| hybrid | 1.000 | 0.907 | 0.924 | 4.0 | 4.2 |

## Recall@5 by category

| Category | n | dense | sparse | hybrid |
|---|---|---|---|---|
| conflicting_versions | 6 | 1.000 | 1.000 | 1.000 |
| direct | 12 | 1.000 | 1.000 | 1.000 |
| exact_policy_id | 5 | 1.000 | 1.000 | 1.000 |
| multi_doc | 2 | 1.000 | 0.583 | 1.000 |
| outdated | 1 | 1.000 | 1.000 | 1.000 |

## How to read this

- **Dense here is not semantic.** The offline hash embedder is feature-hashed bag-of-words, i.e. another lexical model. These numbers say nothing about `text-embedding-3-small`; rerun with `--provider openai` for that comparison.
- **Small corpus.** 38 chunks, so the top 5 already covers 13% of the corpus and Recall@5 saturates easily. MRR and nDCG separate the modes better; a larger corpus is needed before drawing conclusions.
- Chunked with the `simple` tokenizer, not tiktoken; chunk boundaries may differ slightly from production.
- Labels are hand-written and unreviewed; categories with n < 5 are anecdotal.
- Latency covers query embedding plus Qdrant search on the machine that ran the benchmark; it excludes Postgres rechecks and generation.
