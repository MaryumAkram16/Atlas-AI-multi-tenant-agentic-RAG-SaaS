# 0003. Qdrant BM25 sparse vectors for keyword search

- Status: Accepted (fusion moved client-side, see ADR 0006)
- Date: 2026-11-25

## Context
Dense embeddings (`text-embedding-3-small`) capture meaning but miss exact
terms such as policy IDs ("REF-2026-07"), product codes and names. The
blueprint calls for hybrid retrieval: 20 dense plus 20 sparse candidates fused
with Reciprocal Rank Fusion (RRF). The sparse implementation was left open.

Options considered:
- Postgres full-text search, fused in application code;
- a separate search engine (OpenSearch/Elasticsearch);
- learned sparse models (SPLADE);
- BM25 sparse vectors stored in Qdrant next to the dense vectors.

## Decision
Store a BM25 sparse vector alongside the dense vector on every Qdrant point
(named vectors `dense` and `sparse`), using Qdrant's IDF modifier so document
frequency statistics are maintained by the index. Run both searches in a single
Qdrant query with prefetch and RRF fusion, using the **same mandatory payload
filter** (`organization_id`, allowed `document_id`s) on both branches.

## Consequences
- One index, one filter path and one place to enforce tenant filters, so the
  keyword branch cannot be forgotten in a filter review.
- No extra service to run or secure; BM25 needs no GPU or model hosting.
- Sparse tokenization happens in our code (or via a FastEmbed BM25 model),
  so tokenizer choice affects recall and must be benchmarked.
- IDF statistics are collection-wide (shared across tenants). They only affect
  ranking, not access, but are noted as a minor cross-tenant signal.
- Qdrant is still only an index: every candidate is rechecked against Postgres
  ACLs before text is loaded (see CLAUDE.md security rules).
- SPLADE or a cross-encoder reranker can be evaluated later against this
  baseline (Week 6 comparison).
