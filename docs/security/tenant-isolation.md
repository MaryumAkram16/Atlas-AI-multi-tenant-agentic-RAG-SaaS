# Tenant isolation

How a request is authorized, and what the database enforces on its own. The
reasoning is in [ADR 0004](../decisions/0004-tenant-isolation-model.md).

## Request path

1. `Authorization: Bearer <Supabase JWT>` is verified on every request:
   signature (JWKS or HS256 secret, algorithms fixed by server config),
   `iss`, `aud`, `exp`, `iat`, a UUID `sub`, and `role = authenticated`.
   Failure → `401`.
2. Org-scoped routes (`/v1/organizations/{org_id}/...`) look up an **active**
   membership for that user and org. None → `404`.
3. Role rules (`app/tenants/rules.py`) → `403` with a reason.
4. Queries run as `authenticated` with the user's claims; RLS re-applies all of
   the above. A policy refusal → `403 {"detail": "not allowed"}`.

## Roles

| Action | owner | admin | member | viewer |
|---|---|---|---|---|
| Read org, list members | ✓ | ✓ | ✓ | ✓ |
| Invite admin | ✓ | | | |
| Invite member / viewer | ✓ | ✓ | | |
| List invitations | ✓ | ✓ | | |
| Change role of admin | ✓ (to admin/member/viewer) | | | |
| Change role of member / viewer | ✓ (to admin/member/viewer) | ✓ (to member/viewer) | | |
| Revoke admin | ✓ | | | |
| Revoke member / viewer | ✓ | ✓ | | |
| Change own role / revoke self | | | | |
| Grant `owner` | | | | |

## RLS policy matrix

| Table | SELECT | INSERT | UPDATE | DELETE |
|---|---|---|---|---|
| `organizations` | active member | denied (via `create_organization`) | owner (`name` only) | owner (no grant yet) |
| `organization_members` | active member of the org | denied (via `create_organization` / `accept_invitation`) | rules above; columns `role`, `status`, `revoked_at` only | denied (revoke instead) |
| `organization_invitations` | owner/admin | owner, or admin for member/viewer; `invited_by` must be self | owner/admin (`revoked_at` only) | owner/admin |

`anon` has no privileges on any tenant table. `atlas_api` has none until it
switches to `authenticated`, and it cannot switch to `anon`, `service_role`,
`postgres` or `supabase_admin`.

## Documents (Week 2)

Document access is decided by `app_private.document_access()` ([ADR 0005](../decisions/0005-ingestion-pipeline.md)):

| Document | owner | admin | member | viewer |
|---|---|---|---|---|
| Organization-visible, uploaded by someone else | read, write | read, write | read | read |
| Organization-visible, uploaded by me | write | write | write | n/a (viewers can't upload) |
| Restricted, uploaded by someone else, no permission row | none | none | none | none |
| Restricted, with a `read` / `write` permission row | per row | per row | per row | read |

"Write" covers new versions, reindex and delete. Org role never overrides a
restricted document's ACL. Versions, chunks and jobs follow the document.

| Table | SELECT | INSERT | UPDATE | DELETE |
|---|---|---|---|---|
| `documents` | member, and org-visible or owner or permission | owner/admin/member as `owner_id = self` | write access (`title`, `visibility`) | denied (deletion job) |
| `document_versions` | document readable | write access, `created_by = self` | denied (worker publishes) | denied |
| `document_permissions` | own row, or document write access | write access, `granted_by = self` | write access | write access |
| `document_chunks` | document readable | denied (worker only) | denied | denied |
| `ingestion_jobs` | own job, or document readable | write access on the document | denied | denied |

The worker role (`atlas_worker`) has its own policies on documents, versions,
chunks and jobs, all pinned to `app.organization_id`, the tenant of the job
being processed. It can only delete documents already marked `deleting`, cannot
read memberships, and cannot switch to `authenticated`.

Files: stored under `<org>/<document>/<version>/` (DB CHECK constraint), served
only through signed URLs that expire in at most 300 seconds, issued after the
API checks access. Qdrant payloads contain IDs only.

## Chat (Week 3)

Order of checks for `POST /chat` ([ADR 0006](../decisions/0006-baseline-rag.md)):

1. JWT + active membership (as everywhere).
2. Conversation must belong to the caller (RLS); requested `document_ids` must
   all be readable, ready documents, else 404.
3. Qdrant queries filter by `organization_id` + allowed document IDs + their
   current version IDs.
4. Candidate chunk IDs are rechecked under RLS and must belong to an allowed,
   ready document's current published version. Text is loaded only here.
5. Only those chunks reach the model, wrapped as untrusted `<source>` data.

| Table | SELECT | INSERT | UPDATE | DELETE |
|---|---|---|---|---|
| `conversations` | own, while a member | own, while a member | own (`title`) | own |
| `messages` | in own conversation | in own conversation | denied | denied |
| `message_citations` | own message AND document readable now | same | denied | denied |
| `usage_events` | own; owners/admins see the org | own | denied | denied |

## Agent (Week 4)

The LangGraph agent never holds identity in its state. `AuthContext`
(organization, user, role, allowed documents and versions) is frozen, built by
the server after the checks above, and passed outside the state; retrieval and
the Postgres recheck read scope only from it. `validate_context` rejects a
mutable context or identity keys in state, and LangGraph drops unknown input
keys. Document text reaches the model only inside `<source>` blocks marked as
untrusted; instructions in documents cannot widen the search (tested with an
injected "change organization_id" document).

## Web app (Week 5)

The React app only decides which controls to show from the user's role
(`frontend/src/services/permissions.ts`); every action is enforced by the API and
RLS. Answers and source excerpts render as text, never HTML. Member emails come
from the verified JWT (migration 0005), and source previews
(`GET .../documents/{id}/chunks/{chunk_id}`) go through the same RLS check as
retrieval, so a restricted or other-tenant chunk returns 404
(`test_source_preview_is_tenant_scoped`, `test_source_preview_respects_document_acls`).

## Evidence

| Requirement | Tests |
|---|---|
| Authorized reads succeed | `test_owner_lists_own_org`, `test_every_role_can_read_org_and_members`, `test_authorized_reads_succeed` |
| Cross-tenant reads and listings fail | `test_cross_tenant_*` (API and direct DB) |
| Revoked members lose access | `test_revoked_member_loses_access`, `test_revoked_admin_cannot_manage_members`, `test_revoked_member_loses_db_access` |
| Self-promotion fails | `test_self_role_change_fails`, `test_self_promotion_fails` |
| URL `org_id` tampering fails | `test_url_org_id_tampering_fails`, `test_client_supplied_org_id_in_body_is_ignored` |
| Migrations run from scratch | `test_upgrade_downgrade_upgrade` |
| RLS + four policies on every tenant table | `test_every_tenant_table_has_rls_and_per_command_policies` |

| Nova cannot see or delete Acme documents | `test_nova_cannot_list_or_read_acme_documents`, `test_nova_cannot_delete_or_modify_acme_documents`, `test_nova_db_session_sees_no_acme_rows` |
| Restricted documents hidden in every table | `test_restricted_document_hidden_even_from_owner_and_admin`, `test_restricted_document_rows_hidden_in_every_table` |
| Worker confined to one tenant per job | `test_worker_role_is_pinned_to_the_job_tenant`, `test_worker_cannot_delete_documents_not_marked_for_deletion`, `test_claims_cannot_be_used_by_worker_role` |
| Signed URLs only after authorization | `test_signed_download_url_only_after_authorization` |
| A private document never reaches an unauthorized member's answer or the model | `test_private_document_never_reaches_unauthorized_members` |
| Recheck drops stale index entries (superseded, deleting, out of scope, forbidden) | `test_recheck_rejects_stale_index_entries_directly`, `test_recheck_filters_chunks_even_if_upstream_lets_them_through` |
| Conversations private; revoked members lose history | `test_conversations_are_private`, `test_revoked_member_cannot_chat_or_read_history` |
| Agent identity outside state, immutable, not changeable by documents | `test_auth_context_is_immutable`, `test_identity_cannot_enter_state`, `test_mutable_auth_context_is_rejected`, `test_injected_instructions_in_documents_do_not_change_scope` |

API tests: `backend/tests/security/test_api_isolation.py` and
`test_document_isolation.py`. Direct DB tests as the restricted roles:
`test_rls_direct.py` and the DB tests in `test_document_isolation.py`. Chat:
`test_chat_isolation.py`.

## Known limits

- Invitation tokens are returned to the inviter (no email delivery yet).
- Invitation acceptance trusts the JWT `email` claim; require email
  confirmation in Supabase Auth settings.
- No ownership transfer, org deletion endpoint or audit log yet (Week 6).
- No endpoints to grant document permissions yet (schema and policies exist).
- Revocation hides stored citations immediately, but stored answer text is not
  yet revalidated (Week 6).
