# 0012. In-product evaluations

- Status: Accepted
- Date: 2026-11-25

## Context
The blueprint lists `evaluation_datasets / cases` and `evaluation_runs /
results` in the data model and `POST /evaluations`, `GET /evaluations/{id}`
in the API, so an organization can benchmark the agent on its own documents.
The offline benchmark (`app.evaluation.answer_benchmark`) covers the shared
sample corpus only.

## Decision
- Four tenant tables (migration 0007) with RLS, composite foreign keys and
  per-command policies. Owners and admins manage datasets and run them.
- A case has a question plus any of: expected facts (substrings), expected
  document IDs (must be readable by the author when added), or
  `should_abstain`.
- `POST /evaluations` runs **synchronously** with the full agent, as the
  requesting user (their own AuthContext and readable documents), capped at
  `EVALUATION_MAX_CASES` (default 50) and rate-limited. Each case counts as one
  question for quotas and usage, because it costs the same as one.
- Per-case scores: fact hit, correct abstention, expected document cited.
  Run metrics: fact accuracy, false abstention, abstention accuracy, evidence
  hit rate, citation precision, latency p50/p95, tokens, cost (when priced).
- Results store generated answers, which derive from document text. RLS lets
  another owner/admin read a result only while every source document is
  readable to them (the creator always sees their own). Aggregate metrics stay
  visible. Runs and results are immutable; runs outlive their dataset.

## Consequences
- Long runs hold an HTTP request open (Cloud Run allows 300 s). A worker-based
  run would need user-scoped retrieval in the worker; deferred until datasets
  need more than the cap.
- Fact checks are substring matches: they under-count correct paraphrases.
  LLM-judge faithfulness remains in the offline benchmark only.
