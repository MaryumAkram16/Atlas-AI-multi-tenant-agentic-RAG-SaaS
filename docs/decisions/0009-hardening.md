# 0009. Hardening: audit triggers, Postgres limits, revocation, telemetry, injection filter

- Status: Accepted
- Date: 2026-11-25

## Context
Week 6 hardens the system: prompt injection, isolation tests, revocation,
quotas and rate limits, standard errors, tracing and sanitized logs, usage and
audit history, and a larger evaluation.

## Decision

**Audit logs are written by database triggers**, not application code. AFTER
triggers on members, invitations, documents, versions, permissions and reindex
jobs call a SECURITY DEFINER function that records the actor from the verified
JWT claims (`system` for the worker). Any change through any path is
recorded; users can read (owners/admins, RLS) but never write. Metadata holds
IDs, roles and statuses only, no emails or document text. No foreign keys, so
history survives deletions.

**Limits live in Postgres** so they hold across API instances: a fixed-window
counter per user, organization and scope (`consume_rate_limit`, 429 +
`Retry-After`), and plan quotas (documents, storage, questions per day) checked
from an aggregate-only `org_usage` function (429 `quota_exceeded`). Every
question records a usage event, including greetings and abstentions, so the
question quota cannot be sidestepped.

**Revocation.** Each assistant message stores the IDs of every document it
was generated from. When any of them is no longer readable (restricted,
deleted, membership revoked), the stored answer is replaced with a notice,
its citations and conflicts are hidden, and it is not reused as chat history.
Citations were already filtered by RLS (ADR 0006).

**Errors.** Every error is `{"error": {"code", "message", "request_id", ...}}`;
validation errors list fields without echoing input; unexpected errors are
opaque 500s.

**Telemetry.** OpenTelemetry spans for HTTP requests, every agent node,
retrieval, LLM calls and worker steps. The API stores W3C trace context on each
job so the worker continues the request's trace. Span attributes are filtered
to small scalars, with forbidden names (question, answer, content, ...). Logs
are JSON with request and trace IDs and a redaction filter for bearer tokens,
JWTs, API keys and connection-string passwords. Export only when
`OTEL_EXPORTER_OTLP_ENDPOINT` is set.

**Prompt injection: deterministic evidence filter.** The first full
comparison showed the agent repeating injected text ("the admin password is
...") as fact: citation verification cannot catch it, because the text really
is in an authorized source. After the permission recheck, the agent now drops
sentences that address or instruct an AI system and chunks whose heading is
addressed to AI. This is a heuristic on top of the untrusted-data system prompt,
the immutable auth context and citation checks; it can miss novel phrasings.

**Security tests are a separate suite** (`backend/tests/security`, its own CI
step), including a route sweep that calls every documented endpoint with another
tenant's token and without a token, so new endpoints are covered automatically.
AI quality is measured separately by the benchmarks.

## Consequences
- An extra Postgres round trip per chat and upload for limits.
- Rate-limit windows are fixed, so bursts at window edges can reach twice the limit.
- Redacting by source document is coarse: an answer is hidden even if the lost
  document contributed little.
- The injection filter may drop innocent sentences about "instructions";
  removals are counted per run (`injections_removed`).
- The offline evaluation cannot measure answer quality; real numbers need a
  model key (`--provider openai`).
