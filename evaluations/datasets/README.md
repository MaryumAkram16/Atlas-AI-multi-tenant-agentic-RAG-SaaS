# Evaluation datasets

## hr_refund_v1.jsonl

105 hand-labeled questions over the synthetic Acme corpus in `sample-data/acme/`.

Fields: `id`, `question`, `category`, `relevant` (list of `{document, section}`
pairs: a retrieved chunk is relevant when it comes from that file and its
section path ends with that heading), `expected_answer`, `notes`,
`answer_facts` (strings a correct answer must contain, case-insensitive; a
string-match proxy for correctness, not a judgment of the whole answer) and
`stale_documents` (superseded or outdated files that should not be cited).

| Category | Count | What it tests |
|---|---|---|
| direct | 47 | One clear answer in one section |
| exact_policy_id | 15 | Exact identifiers such as `REF-2026-07` (sparse search) |
| missing_evidence | 15 | Not answerable from the corpus; the system should abstain |
| conflicting_versions | 13 | Superseded vs current policies (refund, leave, shipping) |
| multi_doc | 6 | Needs evidence from more than one section or document |
| prompt_injection | 6 | Questions over `vendor-faq.md`, which embeds an injection payload |
| outdated | 3 | An outdated document contradicts or is the only source |

Questions q01-q30 were the Week 3 starter set; q31-q105 were added in Week 6.
`forbidden_strings` lists payload text an answer must never contain.

`missing_evidence` questions have no relevant chunks; they are excluded from
retrieval metrics and used for abstention metrics (Week 4).

Labels were written by hand and have not been independently reviewed.
