# 0011. Document sharing and visibility changes

- Status: Accepted
- Date: 2026-11-25

## Context
The schema (ADR 0004/0005) already had `document_permissions` with RLS: rows
can be inserted, changed and deleted by anyone whose
`app_private.document_access` is `write`. There were no endpoints or UI.

## Decision
- Endpoints follow the existing policies, no schema change:
  `PATCH /documents/{id}` (title, visibility),
  `GET /documents/{id}/permissions`,
  `PUT /documents/{id}/permissions/{user_id}` (`read` or `write`, upsert),
  `DELETE /documents/{id}/permissions/{user_id}`.
- Write access is required for all four, so owners, write grantees and (for
  organization-visible documents) org owners/admins can share. Read-only
  holders get 403; callers who cannot see the document get 404.
- The API adds grantee checks RLS cannot express cleanly: the grantee must be
  an **active** member of the same organization, cannot be the document owner,
  and viewers can only get `read` (Postgres caps viewers at read anyway).
- Documents now return `access` (the caller's own `read`/`write`, computed by
  Postgres) so the UI shows editing and sharing controls only when allowed.
- Nothing changes in Qdrant. Retrieval asks Postgres for readable document IDs
  on every question and rechecks chunk IDs before the LLM, so grants, revokes
  and visibility changes apply to the next question. Stored answers that used a
  document the reader lost are redacted on read (ADR 0009). Every grant,
  change and revoke is written to the audit log by a trigger.

## Consequences
- A write grantee can widen access (share further or make a document
  organization-visible). This matches "write = full control" and keeps one rule;
  a separate "manage" level can be added later if needed.
- Making a restricted document organization-visible asks for confirmation in
  the UI because it exposes the document to every member at once.
