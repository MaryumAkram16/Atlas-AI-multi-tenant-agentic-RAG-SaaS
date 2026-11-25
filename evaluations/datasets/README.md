# Evaluation datasets

## hr_refund_v1.jsonl

30 hand-labeled questions over the synthetic Acme corpus in `sample-data/acme/`.

Fields: `id`, `question`, `category`, `relevant` (list of `{document, section}`
pairs: a retrieved chunk is relevant when it comes from that file and its
section path ends with that heading), `expected_answer`, `notes`,
`answer_facts` (strings a correct answer must contain, case-insensitive; a
string-match proxy for correctness, not a judgment of the whole answer) and
`stale_documents` (superseded or outdated files that should not be cited).

| Category | Count | What it tests |
|---|---|---|
| direct | 12 | One clear answer in one section |
| conflicting_versions | 6 | 2024 vs 2026 policies; the current one should win |
| exact_policy_id | 5 | Exact identifiers such as `REF-2026-07` (sparse search) |
| multi_doc | 2 | Needs evidence from more than one document |
| outdated | 1 | An outdated document contradicts the current policy |
| missing_evidence | 4 | Not answerable from the corpus; the system should abstain |

`missing_evidence` questions have no relevant chunks; they are excluded from
retrieval metrics and used for abstention metrics (Week 4).

Labels were written by hand and have not been independently reviewed.
