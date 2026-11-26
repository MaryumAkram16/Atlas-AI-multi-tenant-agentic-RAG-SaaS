# 0014. Public demo workspace

- Status: Accepted
- Date: 2026-11-26

## Context
Visitors (for example recruiters) should be able to try Atlas on sample
documents without creating an account, without seeing each other's activity,
and without being able to add content or run up costs.

## Options
- **Shared demo login** (one published email/password). Simple, but anyone can
  change the password and lock others out, and every visitor sees every other
  visitor's conversations.
- **Anonymous sign-in per visitor** (Supabase anonymous users). Each visitor is
  a real, private user with `is_anonymous: true` in the JWT.

## Decision
Anonymous sign-in per visitor (migration 0009):
- The operator picks at most one demo organization in
  `app_private.demo_config` with `python -m app.db.manage demo-config`. No API
  can set it, so no tenant can turn its workspace into the demo.
- `POST /v1/demo/join` calls `app_private.join_demo()`, which only accepts
  anonymous users and inserts a **viewer** membership in the configured
  organization. Revoked visitors stay revoked.
- Anonymous users cannot create organizations (enforced in
  `create_organization` and the API) and cannot accept invitations (they have
  no email). They see only their own membership row, so the member list and
  its emails stay hidden.
- Everything else is the normal model: RLS, document ACLs, per-user private
  conversations, rate limits and the organization's daily question quota.

## Consequences
- Requires anonymous sign-ins (and ideally CAPTCHA) in Supabase Auth, and
  periodic cleanup of old anonymous users.
- Demo usage counts against the demo workspace's quota; when it is used up,
  visitors see the standard quota message until the next day.
