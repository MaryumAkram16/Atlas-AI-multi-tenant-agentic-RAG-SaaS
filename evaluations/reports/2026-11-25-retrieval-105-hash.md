# Retrieval benchmark: 2026-11-25

- Dataset: `evaluations/datasets/hr_refund_v1.jsonl` (89 of 105 questions scored; missing-evidence questions excluded)
- Corpus: `sample-data/acme` (80 chunks)
- Embeddings: hash / feature-hashing (offline) (1536 dims); tokenizer: simple
- Chunks 512/64 tokens; dense k=20, sparse k=20, RRF k=60, fused top 20

## Overall

| Mode | Recall@5 | MRR | nDCG@10 | p50 latency (ms) | p95 latency (ms) |
|---|---|---|---|---|---|
| dense | 0.989 | 0.888 | 0.912 | 2.8 | 3.4 |
| sparse | 0.974 | 0.891 | 0.911 | 2.3 | 2.8 |
| hybrid | 0.989 | 0.890 | 0.913 | 5.7 | 6.7 |

## Recall@5 by category

| Category | n | dense | sparse | hybrid |
|---|---|---|---|---|
| conflicting_versions | 13 | 1.000 | 1.000 | 1.000 |
| direct | 47 | 1.000 | 1.000 | 1.000 |
| exact_policy_id | 15 | 0.933 | 0.867 | 0.933 |
| multi_doc | 6 | 1.000 | 0.944 | 1.000 |
| outdated | 3 | 1.000 | 1.000 | 1.000 |
| prompt_injection | 5 | 1.000 | 1.000 | 1.000 |

## How to read this

- **Dense here is not semantic.** The offline hash embedder is feature-hashed bag-of-words, i.e. another lexical model. These numbers say nothing about `text-embedding-3-small`; rerun with `--provider openai` for that comparison.
- **Small corpus.** 80 chunks, so the top 5 already covers 6% of the corpus and Recall@5 saturates easily. MRR and nDCG separate the modes better; a larger corpus is needed before drawing conclusions.
- Chunked with the `simple` tokenizer, not tiktoken; chunk boundaries may differ slightly from production.
- Labels are hand-written and unreviewed; categories with n < 5 are anecdotal.
- Latency covers query embedding plus Qdrant search on the machine that ran the benchmark; it excludes Postgres rechecks and generation.
