# Deployment runbook

Target: API and worker on Google Cloud Run, frontend on Vercel, database/auth/
storage on a dedicated Supabase project, vectors on Qdrant Cloud
([ADR 0010](decisions/0010-deployment.md)). Steps 1–4 are one-time.

## 1. Supabase project

> Done for this deployment: project `atlas-ai` (ref `gfgnhrgasxqgijmcnivp`,
> region `ap-northeast-1`) exists, the private `documents` bucket is created, and
> Vercel has `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY`. Remaining: reset and
> note the database password, set the Auth Site URL, copy the service_role key
> and legacy JWT secret for step 3. Use a matching GCP region (`asia-northeast1`).

1. Create a project named `atlas-ai` (not one shared with another app). Note the
   **project ref**, the **database password**, and from **Connect** the
   **transaction pooler host** (e.g. `aws-0-eu-west-1.pooler.supabase.com`).
2. Storage → create a **private** bucket named `documents`.
3. Auth → URL configuration: set **Site URL** to the Vercel URL and add it to
   the redirect allow list. Keep email confirmation on.
4. Project settings → API: copy the **anon** key (browser) and the
   **service_role** key (server-side Storage only).

## 2. Qdrant Cloud

Create a free cluster; note its URL and API key.

## 3. Google Cloud (Cloud Shell)

```bash
git clone https://github.com/MaryumAkram16/Atlas-AI-multi-tenant-agentic-RAG-SaaS && cd Atlas-AI-multi-tenant-agentic-RAG-SaaS
```

```bash
PROJECT_ID=<gcp-project> REGION=europe-west1 SUPABASE_REF=<ref> SUPABASE_POOLER_HOST=<pooler-host> BILLING_ACCOUNT=<billing-account-id> bash infrastructure/gcp/setup.sh
```

The script prompts for the Supabase database password, OpenAI key, Qdrant key,
Supabase service_role key and legacy JWT secret (tokens signed with the
project's asymmetric keys are verified via JWKS; HS256 ones with the secret), stores them in Secret Manager (never printed),
generates the `atlas_api`/`atlas_worker` database passwords, sets up keyless
GitHub deploys, the worker schedule and a budget alert, and prints the GitHub
variables to add.

## 4. GitHub `production` environment

Settings → Environments → `production` → Variables:

| Variable | Example |
|---|---|
| `GCP_PROJECT_ID`, `GCP_REGION`, `GCP_WIF_PROVIDER`, `GCP_DEPLOY_SA` | printed by `setup.sh` |
| `SUPABASE_URL` | `https://<ref>.supabase.co` |
| `QDRANT_URL` | `https://<cluster>.cloud.qdrant.io:6333` |
| `CORS_ALLOWED_ORIGINS` | `https://atlas-ai-lake-sigma.vercel.app` |
| `LLM_MODEL` (optional) | `gpt-4o-mini` |
| `LLM_INPUT_PRICE_PER_1M`, `LLM_OUTPUT_PRICE_PER_1M` (optional) | from your provider's price list |
| `API_MAX_INSTANCES` (optional) | `3` |

Optionally require a reviewer on the environment so deploys need approval.

## 5. Deploy

Merge to `main`. CI runs; when it passes, **Deploy** builds the image, runs
migrations (`atlas-migrate`), deploys `atlas-api` and `atlas-worker`, and checks
`/ready`. The API URL is in the run summary. Manual run: Actions → Deploy → Run.

## 6. Frontend (Vercel)

Project `atlas-ai` → Settings → Environment Variables (Production):
`VITE_SUPABASE_URL=https://<ref>.supabase.co`, `VITE_SUPABASE_ANON_KEY=<anon key>`,
`VITE_API_URL=<Cloud Run API URL>`, then redeploy. Set the production branch to
`main`.

## 7. Verify

```bash
ATLAS_API_URL=<api-url> SUPABASE_URL=https://<ref>.supabase.co SUPABASE_ANON_KEY=<anon> DEMO_ACME_EMAIL=<you+acme@...> DEMO_NOVA_EMAIL=<you+nova@...> DEMO_PASSWORD=<pw> python scripts/demo.py
```

(Confirm both demo emails first; Supabase sends confirmation links.)

## Before going public

- Budget alert created (step 3), Cloud Run max instances capped, OpenAI usage
  limit set in the OpenAI dashboard, app quotas reviewed (`QUOTA_*`).
- Rollback: Cloud Run → `atlas-api` → Revisions → route traffic to the previous
  revision. Migrations are forward-only in production; test downgrades locally.
