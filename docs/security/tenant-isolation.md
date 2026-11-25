# Tenant isolation (Week 1)

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

API tests: `backend/tests/security/test_api_isolation.py`. Direct DB tests as
the restricted role: `backend/tests/security/test_rls_direct.py`.

## Known limits

- Invitation tokens are returned to the inviter (no email delivery yet).
- Invitation acceptance trusts the JWT `email` claim; require email
  confirmation in Supabase Auth settings.
- No ownership transfer, org deletion endpoint or audit log yet (Week 6).
