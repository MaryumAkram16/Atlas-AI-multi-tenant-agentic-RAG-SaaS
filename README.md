# Atlas AI

Multi-tenant agentic RAG SaaS. Organizations upload documents (PDF, DOCX, TXT,
MD) and ask questions; answers are grounded with citations, flag version
conflicts, and abstain when evidence is weak.

> **Status: scaffold (Prompt 0).** Only `/health` and `/ready` exist so far.
> Features, targets and metrics in the
> [blueprint](docs/Atlas_AI_RAG_Project_Blueprint.pdf) are planned, not
> implemented or measured.

## Stack
FastAPI · Pydantic · Supabase Postgres/Auth/Storage · Qdrant (dense + BM25
sparse, RRF) · Postgres-backed job queue · LangGraph · React + TypeScript ·
Docker Compose · GitHub Actions · OpenTelemetry. See [CLAUDE.md](CLAUDE.md)
for the security rules and layout, and [docs/decisions](docs/decisions) for ADRs.

## Local setup

Requirements: Docker with Compose v2. Python 3.12+ for running tests outside
Docker.

```bash
cp .env.example .env
```

```bash
docker compose up --build
```

This starts:

| Service | URL / port | Notes |
|---------|-----------|-------|
| `api` | http://localhost:8000 | FastAPI; docs at `/docs` |
| `worker` | (no port) | Placeholder; idles until the Week 2 job queue |
| `db` | localhost:54322 | `supabase/postgres` image, user `postgres` |
| `qdrant` | http://localhost:6333 | Dashboard at `/dashboard` |

Check it:

```bash
curl localhost:8000/health
```

```bash
curl localhost:8000/ready
```

`/health` is liveness (process up). `/ready` checks Postgres and Qdrant and
returns `503` with per-check results if either is unreachable.

Stop and remove data:

```bash
docker compose down --volumes
```

## Development

```bash
cd backend && python -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]'
```

```bash
ruff check . && ruff format --check .
```

```bash
pytest -m "not integration"
```

Integration tests run against the compose stack (start it first):

```bash
ATLAS_REQUIRE_STACK=1 pytest -m integration
```

CI (`.github/workflows/ci.yml`) runs lint, format check and unit tests, then
boots the compose stack and runs the integration tests against it.

## Repository layout

```
backend/app/        api, auth, tenants, documents, ingestion, retrieval,
                    agents/{graph,state,nodes,tools}, security, models, schemas,
                    repositories, services, workers, middleware, evaluation,
                    observability
backend/migrations  Alembic migrations (Week 1)
backend/tests/      unit, integration, security, e2e
frontend/src/       React app (Week 5)
evaluations/        datasets, benchmarks, reports
docs/               architecture, security, api, evaluation, decisions (ADRs)
```

## License
MIT. See [LICENSE](LICENSE).
