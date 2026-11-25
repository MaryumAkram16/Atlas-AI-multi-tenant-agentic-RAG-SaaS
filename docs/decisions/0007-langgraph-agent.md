# 0007. LangGraph agent: bounded graph, immutable auth context, deterministic checks

- Status: Accepted
- Date: 2026-11-25

## Context
Week 4 replaces the baseline pipeline with an agent that plans retrieval,
retries on weak evidence, resolves version conflicts and verifies citations.
Requirements: the auth context is server-created, immutable and outside
model-editable state; knowledge questions must retrieve; weak evidence leads to
a rewrite or abstention; failed citation checks lead to a correction or
abstention; max steps, timeouts and token limits; conflicts use effective dates
and explicit precedence and report uncertainty when ambiguous.

## Decision

**Graph.** 14 nodes (validate_context, classify_intent, plan_retrieval,
decompose_query, retrieve_documents, validate_permissions, rerank_results,
assess_evidence, rewrite_query, detect_conflicts, compare_versions,
generate_answer, verify_citations, finalize_response) in a LangGraph
`StateGraph`. Loops: assess → rewrite → retrieve (max `AGENT_MAX_REWRITES`,
then abstain) and verify → generate (max `AGENT_MAX_CORRECTIONS`, then keep
only supported sentences or abstain).

**Identity outside state.** `AuthContext` (organization, user, role, search
scope) is a frozen dataclass built from the verified request and passed in the
run config, not the state. Retrieval and the Postgres recheck read it from
there only. `validate_context` rejects a missing or mutable context and
identity keys in state; LangGraph also drops input keys outside the state
schema. Nothing the model or a document produces can change scope.

**What is deterministic, what may use the model.** Intent routing is
heuristic only, so a model can never route a knowledge question away from
retrieval (greetings and empty questions return directly). Conflict detection,
version comparison and citation verification are deterministic code: auditable
and testable without a model. Query decomposition, rewriting and the
sufficiency judgement use the LLM when `LLM_PROVIDER=openai`, with heuristics as
a floor and fallback on any error or malformed output (model output is parsed
as JSON data, never executed).

**Conflicts.** Documents whose on-topic evidence gives different figures in
the same unit form a conflict. Resolution order: `Status: Outdated`, explicit
`Supersedes:` lines, scoped exceptions ("overriding ... REF-x"), then later
effective date (marked *inferred*); otherwise *ambiguous* and the uncertainty is
reported. For normal questions, explicitly superseded and outdated documents
are left out of the generator's sources (unless the user names that policy);
comparisons keep every version (including superseded versions of the same
document, via an explicit history scope). Conflicts are returned in the
response.

**Verification.** Every factual sentence must cite an existing source; its
figures must appear in the cited source and at least half its topic terms.
Only verified text is streamed: the API streams `step` events while the graph
runs, then the final answer. This trades token-by-token streaming for never
showing unverified claims.

**Limits.** `AGENT_MAX_STEPS` (state guard plus LangGraph recursion limit),
`AGENT_TIMEOUT_SECONDS` for the whole run, `LLM_MAX_TOKENS` per call and an
evidence token budget. Each run gets a `trace_id`; the node trace (names and
timings, no content) is stored with the message.

**Reranking** is lightweight (fused score + topical coverage + policy-ID
boost) behind the node boundary; a cross-encoder remains a Week 6 experiment.

## Consequences
- Offline (extractive generator, heuristic reasoner) the agent already beats
  the baseline on stale citations and abstention in the first benchmark, but
  it is slower and the heuristics are rough; answer quality needs a real model.
- Heuristic sufficiency can wrongly abstain or accept; with a model it becomes
  model judgement above a coverage floor.
- Conflict detection keys on numeric facts; disagreements without numbers
  (e.g. "allowed" vs "not allowed") are not detected yet.
- No token streaming of the answer.
