# InsPoly Funding/HER/Strong Risk Integrity Audit

- Date: 2026-05-22
- Scope: sensitive gate integrity after Side/Outcome Phase 2 and Phase 4
- Machine output: `validation_outputs/inspoly_sensitive_gate_integrity_audit_20260522.json`
- Runtime implementation in this program: false
- Network/RPC used: false
- Gate decision: `sensitive_gate_integrity_preserved_local_only`

## Current Evidence

Side/Outcome changes overlap sensitive contexts indirectly, but source scans do not show direct gate migration.

| Metric | Count |
|---|---:|
| post-replay sensitive rows | 6,819 |
| post-replay sensitive unique trade keys | 2,573 |
| Phase 2 sensitive affected rows | 697 |
| Phase 2 sensitive affected unique trade keys | 102 |
| direct gate migration detected | false |
| Phase 3 capital helper uses Side/Outcome | false |

## Integrity Findings

- Phase 2/4 semantic changes can affect evidence adjacent to Strong Risk/HER/funding narratives.
- Direct Strong Risk/HER/funding/candidate-admission rules were not changed in this campaign.
- Phase 3 remains blocked, which protects size/funding-sensitive interpretation from unsafe capital normalization.

## What Remains Blocked

- Strong Risk label/threshold changes.
- HER routing changes.
- Funding eligibility changes.
- Candidate admission changes.
- Any direct gate behavior change.

## Allowed Local Work

- Sidecar sensitive-case review packets.
- No-runtime audit expansion.
- Manual analyst review of existing packets.

## Approval Required

- Any direct sensitive gate behavior change.
- Any scoring weight/threshold tuning.
- Any live/RPC rerun used to justify gate changes.

## Gate Decision

Decision: `sensitive_gate_integrity_preserved_local_only`.

Sensitive overlap is real, but current evidence supports only audit/review, not direct gate changes.
