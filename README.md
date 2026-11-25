# Atlas AI

Multi-tenant agentic RAG SaaS. Organizations upload documents (PDF, DOCX, TXT,
MD) and ask questions; answers are grounded with citations, flag version
conflicts, and abstain when evidence is weak.

> **Status: Week 4, agentic RAG.** Multi-tenant foundation with RLS (Week 1),
> document ingestion into Qdrant (Week 2), hybrid search with a Postgres
> permission recheck (Week 3), and a bounded LangGraph agent that plans
> retrieval, rewrites weak queries, resolves version conflicts, verifies
> citations and abstains when evidence is weak (Week 4). No frontend yet.
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
| `migrate` | (exits) | Runs migrations, enables the `atlas_api` login, then exits |
| `api` | http://localhost:8000 | FastAPI; docs at `/docs` |
| `worker` | (no port) | Ingestion worker: parse, chunk, embed, index, publish |
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

### Try the API with seed data

Seed the synthetic orgs **Acme** (alice owner, aaron admin, amy member, avery
viewer) and **Nova** (nina owner, noah member):

```bash
docker compose run --rm migrate python -m app.db.manage seed
```

Mint a local token for a seed user (works only with `APP_ENV=local|test` and
the local `SUPABASE_JWT_SECRET`):

```bash
TOKEN=$(docker compose exec -T api python -m app.db.manage dev-token alice@acme.example)
```

```bash
curl -H "Authorization: Bearer $TOKEN" localhost:8000/v1/organizations
```

Endpoints so far:

| Method | Path | Who |
|---|---|---|
| POST, GET | `/v1/organizations` | any signed-in user (GET lists own orgs) |
| GET | `/v1/organizations/{org_id}` | members |
| GET | `/v1/organizations/{org_id}/members` | members |
| POST | `/v1/organizations/{org_id}/members` | owner/admin: invite by email, returns a one-time token |
| PATCH, DELETE | `/v1/organizations/{org_id}/members/{member_id}` | owner/admin: change role, revoke |
| GET | `/v1/organizations/{org_id}/invitations` | owner/admin |
| POST | `/v1/invitations/accept` | the invited user (email must match the JWT) |
| POST, GET | `/v1/organizations/{org_id}/documents` | upload (owner/admin/member; PDF, DOCX, TXT, MD); list visible documents |
| GET, DELETE | `/v1/organizations/{org_id}/documents/{id}` | read with versions; delete (write access, runs as a job) |
| POST | `/v1/organizations/{org_id}/documents/{id}/versions` | upload a new version (write access) |
| POST | `/v1/organizations/{org_id}/documents/{id}/reindex` | reprocess the current version (write access) |
| GET | `/v1/organizations/{org_id}/documents/{id}/versions/{vid}/download-url` | short-lived signed URL (readers) |
| GET | `/v1/organizations/{org_id}/jobs/{id}` | ingestion job status |
| POST | `/v1/organizations/{org_id}/chat` | ask the agent (all roles); SSE (`meta`, `step`, `delta`, `citations`, `done`) with `Accept: text/event-stream`, else JSON with `status`, `evidence_status`, `citations`, `conflicts`, `retrieval_attempts`, `trace_id` |
| GET | `/v1/organizations/{org_id}/conversations[/{id}]` | own conversations, messages and citations |

Upload a document and watch it get indexed:

```bash
curl -H "Authorization: Bearer $TOKEN" -F file=@sample-data/acme/refund-policy-2026.md \
  localhost:8000/v1/organizations/0a000000-0000-4000-8000-000000000001/documents
```

Ask a question (after the worker has indexed it):

```bash
curl -N -H "Authorization: Bearer $TOKEN" -H "Accept: text/event-stream" \
  -H "Content-Type: application/json" -d '{"question": "How many days do customers have to request a refund?"}' \
  localhost:8000/v1/organizations/0a000000-0000-4000-8000-000000000001/chat
```

Locally `EMBEDDING_PROVIDER=hash` and `LLM_PROVIDER=extractive` run without any
API key: deterministic offline vectors with no semantic quality, and an
extractive generator that quotes matching sentences. Set both to `openai` with
`OPENAI_API_KEY` for real embeddings and answers (then reindex).

## Evaluation

Two benchmarks over 30 labeled questions ([how to run](evaluations/benchmarks/README.md)):
retrieval (dense vs sparse vs hybrid) and answers (Week 3 baseline vs the
agent). The reports so far ([index](evaluations/reports/README.md)) were run
offline: hash embeddings, an extractive generator and a 38-chunk corpus. They
check the pipeline and the agent's routing, conflict handling and abstention;
they are not quality measurements. Blueprint targets (e.g. Recall@5 ≥ 85%,
faithfulness ≥ 90%) are targets, not results.

How isolation works and what is tested: [docs/security/tenant-isolation.md](docs/security/tenant-isolation.md).

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

Security, ingestion and migration tests need Postgres and Qdrant (they create
and migrate a throwaway `atlas_test` database and a test collection):

```bash
docker compose up -d db qdrant
```

```bash
pytest -m "not integration"
```

Integration tests run against the full, seeded compose stack:

```bash
ATLAS_REQUIRE_STACK=1 pytest -m integration
```

New migration (plain SQL in `op.execute`, see `backend/migrations/versions`):

```bash
alembic revision -m "describe change"
```

CI (`.github/workflows/ci.yml`) runs lint, format check, and the unit, security
and migration tests against Postgres, then boots and seeds the compose stack
and runs the integration tests against it.

## Repository layout

```
backend/app/        api, auth, tenants, documents, ingestion, retrieval,
                    agents/{graph,state,nodes,tools}, security, models, schemas,
                    repositories, services, workers, middleware, evaluation,
                    observability
backend/migrations  Alembic migrations (plain SQL, RLS policies)
backend/tests/      unit, integration, security, e2e
frontend/src/       React app (Week 5)
evaluations/        datasets, benchmarks, reports
docs/               architecture, security, api, evaluation, decisions (ADRs)
```

## License
MIT. See [LICENSE](LICENSE).
