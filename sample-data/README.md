# Sample data

Synthetic documents for local testing and evaluation. All companies, people
and policies are fictional.

| File | Org | Notes |
|---|---|---|
| `acme/refund-policy-2024.md` | Acme | 14-day refund window, effective 2024-01-01 |
| `acme/refund-policy-2026.md` | Acme | 7-day window, supersedes 2024, effective 2026-01-01 |
| `acme/premium-support-policy.md` | Acme | Premium refund exception |
| `acme/hr-leave-policy-2024.md` | Acme | 20 days leave, 5 carryover (superseded) |
| `acme/hr-leave-policy-2026.md` | Acme | 25 days leave, 10 carryover, parental leave |
| `acme/expenses-policy.md` | Acme | FIN-EXP-03 receipts, meals, approvals, travel |
| `acme/remote-work-policy.md` | Acme | HR-REMOTE-01 remote days, core hours, stipend |
| `acme/it-security-policy.md` | Acme | IT-SEC-05 passwords, MFA, incidents |
| `acme/customer-service-handbook-2023.md` | Acme | Outdated 2023 handbook (30-day refunds) |

The evaluation dataset that uses these files is in
`evaluations/datasets/hr_refund_v1.jsonl`.
