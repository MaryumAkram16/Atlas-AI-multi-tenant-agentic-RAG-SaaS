# Architecture Decision Records

Short records of key choices. Copy `template.md` for a new one, number it
sequentially, and add it to the index below.

| # | Title | Status |
|---|-------|--------|
| [0001](0001-modular-monolith.md) | Modular monolith plus separate worker | Accepted |
| [0002](0002-postgres-backed-job-queue.md) | Postgres-backed job queue | Accepted |
| [0003](0003-qdrant-bm25-sparse-vectors.md) | Qdrant BM25 sparse vectors for keyword search | Accepted |
| [0004](0004-tenant-isolation-model.md) | Tenant isolation: restricted role, JWT claims and RLS | Accepted |
| [0005](0005-ingestion-pipeline.md) | Ingestion pipeline, worker role and document ACLs | Accepted |
| [0006](0006-baseline-rag.md) | Baseline RAG: retrieval, recheck, generation and citations | Accepted |
| [0007](0007-langgraph-agent.md) | LangGraph agent: bounded graph, immutable auth context, deterministic checks | Accepted |
| [0008](0008-frontend-and-local-auth.md) | Frontend: React SPA on one origin, real Supabase Auth locally | Accepted |
| [0009](0009-hardening.md) | Hardening: audit triggers, Postgres limits, revocation, telemetry, injection filter | Accepted |
| [0010](0010-deployment.md) | Deployment: Cloud Run, Supabase, Qdrant Cloud, Vercel | Accepted |
| [0011](0011-document-sharing.md) | Document sharing and visibility changes | Accepted |
| [0012](0012-in-product-evaluations.md) | In-product evaluations | Accepted |
| [0013](0013-answer-feedback.md) | Answer feedback | Accepted |
| [0014](0014-public-demo-workspace.md) | Public demo workspace | Accepted |
