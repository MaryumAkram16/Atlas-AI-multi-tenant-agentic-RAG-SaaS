#!/usr/bin/env bash
# One-time Google Cloud setup for Atlas AI. Run in Cloud Shell:
#
#   PROJECT_ID=my-project REGION=europe-west1 \
#   SUPABASE_REF=abcd1234 SUPABASE_POOLER_HOST=aws-0-eu-west-1.pooler.supabase.com \
#   BILLING_ACCOUNT=XXXXXX-XXXXXX-XXXXXX bash infrastructure/gcp/setup.sh
#
# It creates (idempotently): APIs, an Artifact Registry repo, least-privilege
# service accounts, keyless GitHub deploys via Workload Identity Federation
# (main branch of this repo only), Secret Manager secrets with generated database
# role passwords, the Cloud Scheduler trigger for the worker job, and a budget
# alert. Secret values are prompted for or generated; nothing is printed.
set -euo pipefail

: "${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-europe-west1}"
GITHUB_REPO="${GITHUB_REPO:-MaryumAkram16/Atlas-AI-multi-tenant-agentic-RAG-SaaS}"
BUDGET_USD="${BUDGET_USD:-25}"
: "${SUPABASE_REF:?set SUPABASE_REF (project reference, e.g. abcd1234)}"
: "${SUPABASE_POOLER_HOST:?set SUPABASE_POOLER_HOST (Dashboard > Connect > Transaction pooler host)}"

gcloud config set project "$PROJECT_ID" >/dev/null
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')

echo "== Enabling APIs"
gcloud services enable run.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com iamcredentials.googleapis.com sts.googleapis.com \
  cloudscheduler.googleapis.com billingbudgets.googleapis.com

echo "== Artifact Registry"
gcloud artifacts repositories describe atlas --location="$REGION" >/dev/null 2>&1 ||
  gcloud artifacts repositories create atlas --repository-format=docker --location="$REGION" \
    --description="Atlas AI images"

echo "== Service accounts"
sa() { echo "$1@${PROJECT_ID}.iam.gserviceaccount.com"; }
for name in atlas-deployer atlas-api atlas-worker atlas-scheduler; do
  gcloud iam service-accounts describe "$(sa $name)" >/dev/null 2>&1 ||
    gcloud iam service-accounts create "$name" --display-name="$name"
done

# Deployer (GitHub Actions): deploy Cloud Run, push images, act as runtime SAs.
for role in roles/run.admin roles/artifactregistry.writer; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --quiet --condition=None \
    --member="serviceAccount:$(sa atlas-deployer)" --role="$role" >/dev/null
done
for runtime in atlas-api atlas-worker; do
  gcloud iam service-accounts add-iam-policy-binding "$(sa $runtime)" --quiet \
    --member="serviceAccount:$(sa atlas-deployer)" --role=roles/iam.serviceAccountUser >/dev/null
done
# Scheduler may only start Cloud Run jobs.
gcloud projects add-iam-policy-binding "$PROJECT_ID" --quiet --condition=None \
  --member="serviceAccount:$(sa atlas-scheduler)" --role=roles/run.invoker >/dev/null

echo "== Workload Identity Federation (keyless GitHub deploys, main branch only)"
gcloud iam workload-identity-pools describe github --location=global >/dev/null 2>&1 ||
  gcloud iam workload-identity-pools create github --location=global --display-name="GitHub"
gcloud iam workload-identity-pools providers describe github --location=global \
  --workload-identity-pool=github >/dev/null 2>&1 ||
  gcloud iam workload-identity-pools providers create-oidc github --location=global \
    --workload-identity-pool=github --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
    --attribute-condition="assertion.repository=='${GITHUB_REPO}' && assertion.ref=='refs/heads/main'"
POOL="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github"
gcloud iam service-accounts add-iam-policy-binding "$(sa atlas-deployer)" --quiet \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/${POOL}/attribute.repository/${GITHUB_REPO}" >/dev/null

echo "== Secrets"
put_secret() { # name value
  gcloud secrets describe "$1" >/dev/null 2>&1 ||
    gcloud secrets create "$1" --replication-policy=automatic >/dev/null
  printf '%s' "$2" | gcloud secrets versions add "$1" --data-file=- >/dev/null
}
ask_secret() { # name prompt
  if gcloud secrets versions access latest --secret="$1" >/dev/null 2>&1; then
    echo "  $1 already set (kept)"; return
  fi
  read -r -s -p "  $2: " value; echo
  put_secret "$1" "$value"
}
gen() { openssl rand -base64 36 | tr -dc 'A-Za-z0-9' | head -c 40; }

if ! gcloud secrets versions access latest --secret=ATLAS_MIGRATION_DATABASE_URL >/dev/null 2>&1; then
  read -r -s -p "  Supabase database password (Project settings > Database): " PGPASS; echo
  API_PW=$(gen); WORKER_PW=$(gen)
  put_secret ATLAS_API_DB_PASSWORD "$API_PW"
  put_secret ATLAS_WORKER_DB_PASSWORD "$WORKER_PW"
  # Session pooler for migrations; transaction pooler for request traffic.
  put_secret ATLAS_MIGRATION_DATABASE_URL \
    "postgresql://postgres.${SUPABASE_REF}:${PGPASS}@${SUPABASE_POOLER_HOST}:5432/postgres"
  put_secret ATLAS_DATABASE_URL \
    "postgresql://atlas_api.${SUPABASE_REF}:${API_PW}@${SUPABASE_POOLER_HOST}:6543/postgres"
  put_secret ATLAS_WORKER_DATABASE_URL \
    "postgresql://atlas_worker.${SUPABASE_REF}:${WORKER_PW}@${SUPABASE_POOLER_HOST}:6543/postgres"
  unset PGPASS API_PW WORKER_PW
else
  echo "  database URLs already set (kept)"
fi
ask_secret OPENAI_API_KEY "OpenAI API key (leave empty to add later)"
ask_secret QDRANT_API_KEY "Qdrant Cloud API key"
ask_secret SUPABASE_SERVICE_ROLE_KEY "Supabase service_role key (server-side Storage only)"
ask_secret SUPABASE_JWT_SECRET "Supabase legacy JWT secret (Project settings > JWT Keys; for HS256 sessions)"

grant() { # secret service-account
  gcloud secrets add-iam-policy-binding "$1" --quiet --role=roles/secretmanager.secretAccessor \
    --member="serviceAccount:$(sa "$2")" >/dev/null
}
for s in ATLAS_DATABASE_URL OPENAI_API_KEY QDRANT_API_KEY SUPABASE_SERVICE_ROLE_KEY \
         SUPABASE_JWT_SECRET; do
  grant "$s" atlas-api
done
for s in ATLAS_WORKER_DATABASE_URL ATLAS_MIGRATION_DATABASE_URL ATLAS_API_DB_PASSWORD \
         ATLAS_WORKER_DB_PASSWORD OPENAI_API_KEY QDRANT_API_KEY SUPABASE_SERVICE_ROLE_KEY; do
  grant "$s" atlas-worker
done

echo "== Worker schedule (every minute; the job drains the queue and exits)"
JOB_URI="https://run.googleapis.com/v2/projects/${PROJECT_ID}/locations/${REGION}/jobs/atlas-worker:run"
if gcloud scheduler jobs describe atlas-worker-drain --location="$REGION" >/dev/null 2>&1; then
  gcloud scheduler jobs update http atlas-worker-drain --location="$REGION" --schedule="* * * * *" \
    --uri="$JOB_URI" --http-method=POST --oauth-service-account-email="$(sa atlas-scheduler)" >/dev/null
else
  gcloud scheduler jobs create http atlas-worker-drain --location="$REGION" --schedule="* * * * *" \
    --uri="$JOB_URI" --http-method=POST --oauth-service-account-email="$(sa atlas-scheduler)" >/dev/null
fi

if [[ -n "${BILLING_ACCOUNT:-}" ]]; then
  echo "== Budget alert (${BUDGET_USD} USD; emails billing admins at 50/90/100%)"
  gcloud billing budgets list --billing-account="$BILLING_ACCOUNT" --format='value(displayName)' |
    grep -qx "atlas-ai" ||
    gcloud billing budgets create --billing-account="$BILLING_ACCOUNT" --display-name="atlas-ai" \
      --budget-amount="${BUDGET_USD}USD" --filter-projects="projects/${PROJECT_ID}" \
      --threshold-rule=percent=0.5 --threshold-rule=percent=0.9 --threshold-rule=percent=1.0
else
  echo "== Skipping budget (set BILLING_ACCOUNT to create one; strongly recommended before going public)"
fi

cat <<OUT

Done. Add these as GitHub variables (Settings > Environments > production > Variables):
  GCP_PROJECT_ID   = ${PROJECT_ID}
  GCP_REGION       = ${REGION}
  GCP_WIF_PROVIDER = ${POOL}/providers/github
  GCP_DEPLOY_SA    = $(sa atlas-deployer)
and the app configuration variables listed in docs/deployment.md.
OUT
