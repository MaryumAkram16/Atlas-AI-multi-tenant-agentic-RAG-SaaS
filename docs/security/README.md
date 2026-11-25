# Security model

The rules (from CLAUDE.md) and where each is enforced and tested. Details:
[tenant-isolation.md](tenant-isolation.md).

| Rule | Enforcement | Evidence |
|---|---|---|
| Postgres is the authority; Qdrant is an index | Scope computed under RLS before search; every chunk ID rechecked under RLS before text is loaded | `test_recheck_*`, `test_private_document_never_reaches_unauthorized_members` |
| Verify JWT and active membership on every request | `current_user` + `org_member` dependencies; non-members get 404 | `test_jwt.py`, `test_route_isolation.py` |
| RLS on every tenant table, per-command policies with WITH CHECK | Migrations 0001–0006 | `test_every_tenant_table_has_rls_and_per_command_policies` |
| Restricted DB roles, never the service role | `atlas_api` (requests), `atlas_worker` (tenant-pinned per job); service key only for Storage calls after authorization | `test_api_login_role_*`, `test_worker_role_is_pinned_to_the_job_tenant` |
| Every Qdrant search filters by org and allowed documents | `VectorIndex._query` requires both | `test_upload_to_searchable_end_to_end` |
| Document content is untrusted; identity outside agent state | `<source>` blocks, frozen `AuthContext`, injection filter, citation checks | `test_prompt_injection.py`, `test_agent_graph.py` |
| Sanitized logs | JSON logs with redaction; span attributes filtered | `test_logging.py`, `test_tracing.py` |
| Audit and revocation | DB-trigger audit logs; answers from now-unreadable sources hidden | `test_audit_logs.py`, `test_revocation.py` |

The security suite (`backend/tests/security`) runs as its own CI step,
separate from AI quality evaluation. These are tested design properties, not
an external security audit.
