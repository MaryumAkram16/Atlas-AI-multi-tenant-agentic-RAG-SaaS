# 0008. Frontend: React SPA on one origin, real Supabase Auth locally

- Status: Accepted
- Date: 2026-11-25

## Context
Week 5 adds the UI: sign-up/login, organizations, knowledge base, chat with
streaming and source previews, member admin. The acceptance test is a new user
doing all of it in the browser, so local auth must be real, not mocked.

## Decision
- **React 18 + TypeScript + Vite**, React Router, `@supabase/supabase-js` for
  auth. No component library or data-fetching framework: a small `apiRequest`
  wrapper, an SSE reader over `fetch` (POST is required, so not `EventSource`)
  and plain CSS with the blueprint palette as variables.
- **One origin.** In compose, nginx serves the app and proxies `/v1` to the API
  and `/auth/v1` to Supabase Auth; Vite's dev server does the same. No CORS
  configuration, cookies or tokens shared across origins. SSE responses are not
  buffered by the proxy.
- **Real Supabase Auth locally.** The `auth` service runs GoTrue against the
  Supabase Postgres image. A `roles.sql` init script (local only, as in
  Supabase's own docker setup) gives `supabase_auth_admin` a password. GoTrue
  signs HS256 tokens with the same secret, issuer and audience the API verifies,
  so the backend runs unchanged. Email auto-confirm is on locally only
  (`AUTH_AUTOCONFIRM`).
- **Role-aware UI, backend-enforced.** `permissions.ts` mirrors the role rules
  only to decide which controls to show; the API and RLS enforce everything.
- **Untrusted content stays text.** Answers and source excerpts are rendered
  as React text nodes (no `dangerouslySetInnerHTML`); downloads use signed URLs
  with `Content-Disposition: attachment`. Post-login redirects only accept
  same-app relative paths.
- **Invitations** produce a one-time link shown to the inviter (no email
  delivery yet); the invitee signs up or in and accepts at `/invite/:token`.
- **Two backend additions:** member emails (copied from the verified JWT when
  a user creates an org or accepts an invite, migration 0005) and a chunk
  preview endpoint for citations, both behind the existing RLS rules.

## Consequences
- The access token lives in browser storage (supabase-js default). Mitigated by
  short JWT expiry, no third-party scripts, and text-only rendering of untrusted
  content; an httpOnly-cookie session would need a backend-for-frontend.
- The Playwright suite needs the whole stack (`docker compose up`) and runs in
  the CI smoke job.
- Answers stream only after verification (ADR 0007): the UI shows agent steps
  ("Searching documents", "Verifying citations") until then.
