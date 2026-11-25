# Atlas AI: Claude Code Prompts

How to use this file:
1. Copy **Part 1** into `CLAUDE.md` at your repo root.
2. Put the blueprint PDF at `docs/Atlas_AI_RAG_Project_Blueprint.pdf`.
3. Run the **Part 2** prompts one at a time, in order. Start each in a fresh session, and only move on when the "Done when" checks pass.

---

## Part 1: CLAUDE.md

```markdown
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
```

---

## Part 2: Phase prompts

### Prompt 0: Scaffold

```
Read CLAUDE.md and docs/Atlas_AI_RAG_Project_Blueprint.pdf.
Scaffold the repo with the folder layout from CLAUDE.md. Add:
- FastAPI app with /health and /ready endpoints
- Docker Compose for the API, worker placeholder, Postgres (Supabase local) and Qdrant
- .env.example with every variable documented
- Pytest setup, ruff, and a GitHub Actions workflow running lint and tests
- README with local setup steps
Write ADRs for: Postgres-backed job queue, Qdrant BM25 sparse vectors, modular monolith.
Done when `docker compose up` works and CI passes.
```

### Prompt 1: Week 1, secure foundation

```
Build the multi-tenant foundation. Write the security tests FIRST.
1. Alembic migrations for organizations, organization_members, organization_invitations.
   Use UUIDs, uniqueness constraints and tenant-scoped composite foreign keys.
2. RLS on each table with separate SELECT/INSERT/UPDATE/DELETE policies and WITH CHECK.
3. Supabase JWT verification (issuer, audience, expiry) and active-membership check middleware.
4. Endpoints: POST/GET /v1/organizations, POST /members, PATCH/DELETE /members/{id}.
5. Role rules: no self-promotion, only owner/admin can change roles.
Seed two synthetic orgs, Acme and Nova.
Done when tests prove, via the API AND direct DB access with restricted roles:
- authorized reads succeed
- cross-tenant reads and listings fail
- revoked members lose access
- self-promotion and URL org_id tampering fail
- migrations run from scratch
Do NOT add LangGraph or embeddings yet.
```

### Prompt 2: Week 2, ingestion

```
Build document ingestion.
1. Tables: documents, document_versions, document_permissions, document_chunks, ingestion_jobs, all with RLS.
2. POST /documents (validate type and size), POST /documents/{id}/versions, GET /documents,
   GET/DELETE /documents/{id}, POST /documents/{id}/reindex, GET /jobs/{id}.
3. Store files at tenant-scoped storage paths. Use short-lived signed URLs after authorization only.
4. Postgres-backed job queue (SELECT ... FOR UPDATE SKIP LOCKED) with idempotency keys,
   bounded exponential backoff and an attempts limit.
5. Worker: parse PDF/DOCX/TXT/MD keeping page numbers and headings, chunk by section
   (512 tokens, 64 overlap), dense + BM25 sparse embeddings, upsert to Qdrant with
   organization_id, document_id, version_id, chunk_id payload.
6. Publish the version atomically in Postgres only after indexing is validated.
7. Checksums for duplicate detection. Safe delete removes vectors and storage.
Done when: upload to searchable works end to end, a failed job retries then fails cleanly,
duplicates are detected, and a Nova user cannot see or delete Acme documents.
```

### Prompt 3: Week 3, baseline RAG

```
Build baseline retrieval and answering.
1. Hybrid search: 20 dense + 20 sparse candidates, RRF fusion, mandatory org and document filters.
2. Recheck every candidate chunk ID against Postgres permissions and published status
   before loading text.
3. Select the top 5-8 chunks and generate a grounded answer with citations
   (document, version, page, section).
4. POST /chat with question, optional conversation_id and optional document_ids (validated).
   Stream the answer with SSE.
5. Tables: conversations, messages, message_citations, usage_events.
6. Create evaluations/datasets with 30 starter labeled questions on HR/refund policies,
   including conflicting versions, outdated docs, missing evidence and exact policy IDs.
7. Benchmark script: Recall@5, MRR, nDCG, latency for dense-only vs hybrid.
Done when chat answers with correct citations, a private doc never appears for an
unauthorized member, and the first benchmark report is saved in evaluations/reports.
```

### Prompt 4: Week 4, agentic RAG

```
Replace the baseline pipeline with a LangGraph agent. Nodes:
validate_context, classify_intent, plan_retrieval, decompose_query, retrieve_documents,
validate_permissions, rerank_results, assess_evidence, rewrite_query (max 2),
detect_conflicts, compare_versions, generate_answer, verify_citations, finalize_response.
Rules:
- The auth context is server-created and immutable, kept outside model-editable state.
- Knowledge questions must retrieve. Greetings return directly.
- Weak evidence leads to a rewrite, or an abstain after the limit.
- A failed citation check leads to a correction, or an abstain.
- Enforce max graph steps, timeouts and token limits.
- Conflicts compare effective dates and explicit precedence, and report uncertainty if ambiguous.
The response adds status, evidence status, conflicts, retrieval attempts and trace_id.
Done when the refund-policy example (2024: 14 days, 2026: 7 days, premium exception)
answers correctly with citations, and the benchmark compares baseline vs agent.
```

### Prompt 5: Week 5, frontend

```
Build the React + TypeScript frontend.
Pages: login/signup (Supabase Auth), org creation and workspace switcher, knowledge base
(upload, versions, ingestion status), chat with streaming and clickable source previews,
conflict and abstain states, member admin (invite, role change, revoke).
Colors: navy #0F1B2D, teal #44D5C0, violet #8B5CF6, slate #94A3B8, white #F8FAFC.
Show UI actions based on role, but rely on the backend for enforcement.
Done when a new user can sign up, create an org, invite a member, upload a doc
and chat with citations entirely in the UI.
```

### Prompt 6: Week 6, hardening

```
Harden the system.
1. Prompt-injection tests: documents containing instructions must not change behavior or permissions.
2. An expanded isolation test suite, kept separate from AI quality evals.
3. On revocation, revalidate access to stored conversations, citations and cached evidence.
4. Per-tenant quotas, standardized error format, rate limits.
5. OpenTelemetry traces across API, agent and worker, with sanitized structured logs.
6. GET /usage and GET /audit-logs, with audit_logs written for sensitive actions.
7. Grow the eval set to 100+ questions. Run the full comparison: dense, hybrid,
   hybrid+rerank, +rewrite, full agent. Track faithfulness, citation correctness, cost.
Done when all security tests pass and the eval report is in evaluations/reports.
```

### Prompt 7: Weeks 7-8, release

```
Prepare the release.
1. Deploy the API and worker to Cloud Run, and the frontend to a host (write an ADR for the choice).
2. CI/CD: test, build, deploy on merge to main, with secrets via GitHub environments.
3. Budget alerts and quotas before going public.
4. Docs: architecture diagram, security model, API reference, evaluation results, ADR index.
5. README: what it does, live demo link, real measured metrics only, local setup, screenshots.
6. A demo script showing Acme vs Nova isolation and the refund-policy conflict answer.
Done when the live demo works and the README shows only verified numbers.
```

---

## Part 3: Handy follow-up prompts

- **Review before merge:** `Review this branch for tenant-isolation bugs, missing RLS, and any path where unauthorized text could reach the LLM.`
- **Fix failing CI:** `CI is failing. Read the logs, find the root cause, fix it, and explain what broke.`
- **Resume work:** `Read CLAUDE.md and git log. Tell me which phase we're in, what's done, and what's next.`
