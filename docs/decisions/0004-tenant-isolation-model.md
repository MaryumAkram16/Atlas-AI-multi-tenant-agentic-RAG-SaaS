# 0004. Tenant isolation: restricted role, JWT claims and RLS

- Status: Accepted
- Date: 2026-11-25

## Context
Postgres is the security authority (CLAUDE.md). Every request must be
authenticated (Supabase JWT) and authorized against an active membership, and
a bug in one query must not leak another tenant's data. Facts about the
Supabase Postgres image that shape this:

- `postgres` has `BYPASSRLS`, and `service_role` bypasses RLS too.
- Default privileges grant `anon` and `authenticated` ALL on new tables and
  EXECUTE on new functions in `public`.
- PostgREST's model is to log in as a NOINHERIT role, `SET ROLE authenticated`
  and expose the JWT claims via `request.jwt.claims`.

## Decision
1. **Restricted login role.** The API and worker connect as `atlas_api`
   (LOGIN, NOINHERIT, NOBYPASSRLS, no table privileges of its own). Each request
   runs in a transaction with `SET LOCAL ROLE authenticated` and
   `set_config('request.jwt.claims', <verified claims>, true)`. Both are
   transaction-local, so pooled connections never carry identity over.
   The schema owner (`postgres`) is used only by migrations and the seed script.
2. **Identity from claims only.** `app_private.current_user_id()` and
   `current_user_email()` read the claims. Functions never take a user ID
   argument.
3. **RLS on every tenant table**, with separate SELECT/INSERT/UPDATE/DELETE
   policies; INSERT/UPDATE have WITH CHECK. Grants are explicit and minimal,
   including column-level UPDATE grants so identity columns
   (`user_id`, `organization_id`) cannot be changed. Supabase's default grants
   to `anon`, `authenticated` and `service_role` are revoked.
4. **Two SECURITY DEFINER entry points** for the operations RLS cannot express
   safely: `create_organization` (org + owner membership atomically) and
   `accept_invitation` (a non-member joining via a hashed, single-use,
   expiring token whose email must match the JWT). Direct INSERTs into
   `organizations` and `organization_members` are denied by policy.
   `member_role()` is also SECURITY DEFINER so member policies don't recurse;
   it only answers for the current user.
5. **Defence in depth in the API.** A dependency verifies the JWT and an active
   membership for the org in the URL on every request (404 for non-members, so
   org existence isn't revealed), and role rules are checked in Python for
   clear 403s. The same rules are enforced again by RLS.
6. **Soft revocation.** Memberships are revoked (`status = 'revoked'`), never
   hard-deleted; revoked users fail every membership check immediately even with
   a still-valid JWT.
7. **No foreign key to `auth.users`.** `user_id` holds the Supabase Auth user
   UUID without a FK, keeping migrations portable (plain Postgres in tests and
   CI, any Supabase project) and runnable on a fresh database.
8. **One owner per org; no ownership transfer yet.** Enforced by a partial
   unique index; `owner` cannot be granted via role changes or invitations.

## Consequences
- A forgotten `WHERE organization_id = ...` returns nothing instead of leaking.
  Tests in `backend/tests/security/test_rls_direct.py` prove this by querying
  as `atlas_api` directly, bypassing the API.
- `atlas_api` is trusted to set claims honestly, so RLS protects against query
  bugs, not a fully compromised API process (same trust model as PostgREST).
  Keep its credentials as secret as the service role key's.
- The definer functions bypass RLS and are security-critical code: keep them
  small, `search_path = ''`, and covered by tests.
- Deleted Supabase users leave orphaned membership rows until a cleanup job
  exists (future work).
- `SELECT ... FOR UPDATE` applies UPDATE policies; avoid it for reads that must
  see rows the caller cannot change.
