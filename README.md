# Atlas AI

Multi-tenant agentic RAG SaaS. Organizations upload documents (PDF, DOCX, TXT,
MD) and ask questions; answers are grounded with citations, flag version
conflicts, and abstain when evidence is weak.

> **Status: Week 1, secure multi-tenant foundation.** Organizations,
> memberships, invitations, roles, Supabase JWT auth and Postgres RLS. No
> documents, retrieval or agent yet.
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

Unit, security and migration tests need Postgres (they create and migrate a
throwaway `atlas_test` database):

```bash
docker compose up -d db
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
