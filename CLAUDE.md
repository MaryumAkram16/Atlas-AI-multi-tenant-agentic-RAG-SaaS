# Atlas AI: multi-tenant agentic RAG SaaS

Companies sign up, create an organization, invite members, upload documents
(PDF, DOCX, TXT, MD) and ask questions. Answers are grounded with citations,
flag version conflicts, and abstain when evidence is weak.
Full spec: docs/Atlas_AI_RAG_Project_Blueprint.pdf

## Stack
- Backend: Python, FastAPI, Pydantic, Alembic, Pytest
- Agent: LangGraph (bounded graph, max steps, timeouts)
- Data/Auth/Storage: Supabase Postgres + Auth + Storage
- Search: Qdrant, dense (text-embedding-3-small) + BM25 sparse, RRF fusion
- Jobs: Postgres-backed queue + separate worker
- Frontend: React + TypeScript
- Ops: Docker Compose, GitHub Actions, OpenTelemetry

## Security rules (never break)
- Postgres is the security authority. Qdrant is only an index.
- Verify the JWT and active membership on every request. Never trust a client org_id.
- RLS on every tenant table, with separate SELECT/INSERT/UPDATE/DELETE policies and WITH CHECK.
- Normal requests use restricted DB roles, never the service role.
- Every Qdrant search filters by organization_id and allowed document_ids.
- Recheck chunk IDs against Postgres ACLs before any text reaches a reranker or LLM.
- Document content is untrusted data. Tenant identity and permissions stay outside agent state.
- Logs are sanitized: no document text, no tokens, no secrets.

## Roles
owner: org and billing. admin: members and authorized docs.
member: upload and chat. viewer: read and chat. Document ACLs apply independently.

## Layout
backend/app/{api,auth,tenants,documents,ingestion,retrieval,agents/{graph,state,nodes,tools},
security,models,schemas,repositories,services,workers,middleware,evaluation,observability}
backend/migrations, backend/tests/{unit,integration,security,e2e}
frontend/src/{components,pages,features,hooks,services}
evaluations/{datasets,benchmarks,reports}, sample-data, infrastructure,
docs/{architecture,security,api,evaluation,decisions}, .github/workflows,
docker-compose.yml, .env.example, README.md, LICENSE

## Working style
- Small PRs, tests with every change, CI must pass before merge.
- Ask before adding a dependency or changing the schema design.
- Record each key choice as a short ADR in docs/decisions.
- No invented metrics in the README. Mark targets as targets.
- Never commit .env or keys.
