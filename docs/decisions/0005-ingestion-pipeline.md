# 0005. Ingestion pipeline, worker role and document ACLs

- Status: Accepted
- Date: 2026-11-25

## Context
Week 2 turns uploads into searchable chunks. The pipeline runs asynchronously
(ADR 0001, 0002), touches every tenant's data, and writes to three stores
(Postgres, object storage, Qdrant) that cannot share one transaction.

## Decision

**Upload (API).** Authorize (member role, document write access) → read with a
size cap → sniff content (PDF magic, DOCX zip with `word/document.xml`, UTF-8
text) → SHA-256 → duplicate check → store the file at
`<org>/<document>/<version>/<file>` → insert document, version and job in one
transaction. If the insert fails, the stored file is removed. A database CHECK
constraint enforces the tenant-scoped storage path.

**Duplicates** are detected by checksum among documents the caller can see.
Hidden documents are ignored on purpose, so a 409 never reveals that a document
the caller cannot read exists.

**Idempotency.** `Idempotency-Key` on upload maps to a unique
`(organization_id, idempotency_key)` job; a replay returns the original
document and job (200). Partial unique indexes allow one active (re)index job
per version and one active delete job per document.

**Worker role.** The worker logs in as `atlas_worker` (NOBYPASSRLS, never the
service role). It claims jobs across tenants only through
`app_private.claim_ingestion_job` (`FOR UPDATE SKIP LOCKED`, increments
attempts, reclaims expired leases). Every later transaction sets
`app.organization_id` to the job's tenant, and all worker RLS policies match only
that tenant. Workers cannot read memberships or switch to `authenticated`.

**Processing.** Parse (pages for PDF, heading paths for MD/DOCX/PDF numbered
headings) → section-aware chunks (512 tokens, 64 overlap, never spanning two
sections, per-token page tracking) → chunk rows → dense + BM25 sparse vectors
→ Qdrant upsert → validate that Qdrant holds exactly the expected number of
points for the version → publish in one Postgres transaction (supersede the old
version, publish the new one, point the document at it, mark the job
succeeded). Chunk IDs are `uuid5(version, index)` and double as Qdrant point
IDs, so retries and reindexing overwrite instead of duplicating.

**Failures.** Retryable errors requeue the job with bounded exponential
backoff and jitter (`base·2^(n-1)` capped, in `[ceiling/2, ceiling]`). After
`max_attempts`, or for permanent errors (no text, document deleted), the job
fails, the version is marked failed and its chunks and vectors are removed. A
failed reindex never unpublishes the live version. Stored error text is the
exception type plus a redacted, truncated message.

**Deletion** is a job: the API marks the document `deleting` through a
definer function that checks write access; the worker deletes the Qdrant points
(by tenant + document filter), the stored files, then the rows. Worker RLS only
allows deleting documents already marked `deleting`. An ingest that races a
delete detects it at publish time and removes its own vectors.

**Document ACLs** (`app_private.document_access`): restricted documents are
visible only to their owner and users with a permission row, whatever their org
role. Viewers never write. Owners/admins can write organization-visible
documents; members can write their own. Versions, chunks and jobs are visible
exactly when the document is.

**Tokenizer and embeddings.** tiktoken `cl100k_base` (the encoding of
`text-embedding-3-small`) is baked into the Docker image. A lossless "simple"
tokenizer exists for environments that cannot download the encoding. Embeddings
sit behind a small interface: OpenAI in production, a deterministic hashing
embedder for local development and tests (no semantic quality; never use it for
evaluation). Qdrant payloads hold IDs only, never text.

**Storage.** `LocalStorage` (dev/test) serves files only via HMAC-signed,
expiring URLs at `/v1/files/...` with `Content-Disposition: attachment`.
`SupabaseStorage` uses the service role key server-side only, after the API has
authorized the request; database sessions never use it.

## Consequences
- Postgres stays the authority: a version is only `published` after its vectors
  are verified, and retrieval (Week 3) must still recheck chunk IDs.
- Three stores without a shared transaction means short windows of orphaned
  vectors or files (e.g. a crash between steps). They are harmless for security
  because Postgres is rechecked, and a cleanup sweep can be added later.
- The worker trusts itself to set `app.organization_id` honestly, the same trust
  model as `atlas_api` setting claims.
- Changing embedding dimensions needs a new collection and a full reindex.
- Leases have no heartbeat yet: a job running longer than `JOB_LEASE_SECONDS`
  can be picked up twice. Processing is idempotent, so the cost is duplicate work.
- No endpoints to manage document permissions yet; the table, policies and
  checks exist.
