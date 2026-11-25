# 0002. Postgres-backed job queue

- Status: Accepted
- Date: 2026-11-25

## Context
Ingestion runs asynchronously in a separate worker (ADR 0001). The blueprint
leaves the durable queue technology open. Requirements:

- durable across restarts, with retries, bounded exponential backoff and an
  attempts limit;
- idempotency keys so a re-sent upload does not create duplicate work;
- tenant-scoped jobs whose status is visible through `GET /jobs/{id}`;
- job state that changes **in the same transaction** as document metadata, so
  a version is only published after indexing is validated.

Options considered: Redis/RQ or Celery, a cloud queue (Pub/Sub, Cloud Tasks),
or a table in the Postgres we already run.

## Decision
Use an `ingestion_jobs` table in Postgres. Workers claim work with
`SELECT ... FOR UPDATE SKIP LOCKED`, track `attempts`, `run_after` (for
backoff) and `last_error`, and enforce a unique idempotency key. Jobs carry
`organization_id` and are covered by RLS like any other tenant table.

## Consequences
- No new infrastructure, cost or credentials; one fewer thing to secure.
- Job state and document state commit atomically, which a separate broker
  cannot offer without an outbox pattern.
- Job history is queryable with SQL for debugging and evaluation.
- Throughput is bounded by Postgres; fine for MVP ingestion volumes. Polling
  adds a little latency (`WORKER_POLL_INTERVAL_SECONDS`); `LISTEN/NOTIFY` can
  reduce it later.
- We own retry and dead-letter logic. If volume outgrows Postgres, revisit
  with a dedicated broker behind the same worker interface.
