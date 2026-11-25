# 0010. Deployment: Cloud Run, Supabase, Qdrant Cloud, Vercel

- Status: Accepted
- Date: 2026-11-25

## Context
The blueprint deploys the API to Cloud Run with a "suitable worker execution
model" and leaves the frontend host open. Budget target: free tiers where
possible, a few dollars a month otherwise.

## Decision
- **API**: Cloud Run service `atlas-api`, scale to zero, max 3 instances,
  concurrency 40, 300 s timeout (SSE answers).
- **Worker**: Cloud Run **job** `atlas-worker` running `--drain` (process due
  jobs, exit), started every minute by Cloud Scheduler. No always-on instance
  is paid for; ingestion can wait up to about a minute. Long documents are
  bounded by a 15-minute task timeout; unfinished jobs resume via lease reclaim.
- **Migrations**: Cloud Run job `atlas-migrate`, executed by every deploy before
  the new API revision rolls out.
- **Frontend**: **Vercel** (the user's choice): static Vite build, git-linked
  deploys, preview URLs. The API allows the Vercel origin via
  `CORS_ALLOWED_ORIGINS` (exact origins, no credentials).
- **Database, auth, storage**: a dedicated Supabase project (not shared with
  other apps: separate auth users and roles). Cloud Run reaches it through the
  Supavisor pooler (IPv4): transaction mode for requests (prepared statements
  disabled), session mode for migrations. JWTs verified via the project's JWKS.
- **Vector index**: Qdrant Cloud (free tier cluster), API key in Secret Manager.
- **CI/CD**: GitHub Actions. `CI` on every push; `Deploy` after CI succeeds on
  `main`, authenticating with **Workload Identity Federation** (no service
  account keys; trust limited to this repo's `main` branch). App secrets live in
  Secret Manager, deploy configuration in the GitHub `production` environment.
- **Cost guards**: a billing budget with 50/90/100% alerts, Cloud Run instance
  caps, app-level per-tenant quotas and rate limits, and an OpenAI usage limit
  set in the OpenAI dashboard.

## Consequences
- Cold starts on the API (scale to zero) add latency to the first request.
- Up to a minute of ingestion delay; an "ingest now" trigger from the API can be
  added later.
- Database role passwords are generated into Secret Manager and never shown.
- Vercel deploys independently of the backend; schema-breaking API changes need
  ordering (deploy the API first).
