# 0001. Modular monolith plus separate worker

- Status: Accepted
- Date: 2026-11-25

## Context
Atlas AI has several domains: tenants and auth, documents, ingestion,
retrieval, the agent, evaluation and observability. It is built and run by a
very small team on a free-tier budget (blueprint section 07). Microservices
would add network hops, deployments, auth between services and distributed
failure modes before we have any evidence we need independent scaling.

The one workload with clearly different runtime needs is ingestion: parsing
and embedding are slow, bursty and must not block API requests.

## Decision
- One FastAPI codebase (`backend/app`) organised by domain package
  (`tenants`, `documents`, `ingestion`, `retrieval`, `agents`, ...).
- Two processes from the same image: the **API** (`uvicorn app.main:app`) and
  the **worker** (`python -m app.workers.main`).
- Domains talk through in-process service interfaces, not HTTP. Data access goes
  through `repositories`, so the boundary between domains stays visible.
- Shared infrastructure: one Postgres (Supabase) and one Qdrant collection.

## Consequences
- Simple local setup (`docker compose up`) and one CI pipeline.
- One deploy artifact; API and worker scale independently on Cloud Run.
- Discipline is needed to keep domain boundaries clean, since nothing enforces
  them at runtime. If a domain later needs to be split out, its package and
  repository layer are the seam.
- A bug in shared code can affect both processes; tests must cover both.
