# 0006. Baseline RAG: retrieval, recheck, generation and citations

- Status: Accepted
- Date: 2026-11-25

## Context
Week 3 answers questions from indexed documents with citations. The security
rules require mandatory tenant and document filters on every Qdrant search and
a Postgres recheck before any text reaches a model. Generation provider is an
open decision in the blueprint; this environment has no LLM key.

## Decision

**Scope first.** Before searching, `allowed_documents()` lists, under RLS,
the caller's readable documents that are `ready` with a published current
version, intersected with any `document_ids` in the request. If any requested
ID is not readable the request fails with 404 (no detail about which).

**Hybrid search, client-side RRF.** Two Qdrant queries (20 dense, 20 BM25
sparse), each filtered by `organization_id`, the allowed document IDs and their
current version IDs, fused with RRF (k = 60) in Python to 20 candidates. This
refines ADR 0003, which planned server-side fusion: client-side fusion lets the
benchmark run dense-only, sparse-only and hybrid through the same code, exposes
per-list ranks, and is unit-tested. It costs one extra round trip.

**Recheck before text.** `load_authorized_chunks()` reloads candidate chunk IDs
under RLS and keeps only chunks of allowed, `ready` documents whose *current*
published version they belong to. This is the only place chunk text is read,
so stale index entries (superseded versions, deleting documents, revoked
access) cannot reach the model. Top 8 survivors become evidence.

**Generation.** Evidence is passed as numbered `<source>` blocks with tag-like
markup neutralized; the system prompt says source text is untrusted data,
requires `[n]` citations, preferring the latest effective date on conflicts,
and an exact sentence when evidence is insufficient. With no evidence the model
is not called. Providers sit behind a streaming interface: OpenAI Chat
Completions (default model `gpt-4o-mini`, temperature 0, configurable) and an
offline *extractive* generator that quotes the best-matching sentences, for
local development and tests only.

**Citations** are the sources the answer actually cites (`[n]` markers),
returned with document, version, effective date, section and pages, and stored
in `message_citations`. Their SELECT policy also requires the document to be
readable *now*, so citations vanish from history when access is lost.

**API.** `POST /v1/organizations/{org}/chat` streams SSE (`meta`, `delta`,
`citations`, `done`, `error`) with `Accept: text/event-stream`, else returns
JSON. Conversations are private to their author while they are an active
member. Usage events record model and tokens; cost is stored only if prices are
configured (`LLM_*_PRICE_PER_1M`), never guessed.

## Consequences
- Baseline answers are only as good as the top-8 evidence; there is no
  reranking, query rewriting, conflict logic or citation verification yet
  (Week 4).
- Stored answer *text* is not yet revalidated on revocation: citations
  disappear, but the answer may still quote a source the user lost access to
  (Week 6, revocation revalidation).
- The extractive generator cannot reason or compare versions; quality numbers
  must come from a real model.
- Query embedding tokens are not yet recorded in `usage_events`.
