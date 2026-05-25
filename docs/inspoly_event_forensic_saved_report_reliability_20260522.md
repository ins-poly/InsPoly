# InsPoly Event Forensic Saved-Report Reliability Replay

- Date: 2026-05-22
- Scope: local saved-report reliability replay for weak-history near-certain later wins
- Machine outputs:
  - `validation_outputs/event_forensic_saved_report_inventory_20260522.json`
  - `validation_outputs/event_forensic_weak_history_saved_report_audit_20260522.json`
- Runtime implementation: false
- Network/RPC used: false
- Saved artifacts mutated: false
- Gate decision: `weak_history_needs_live_rpc_validation`

## Inventory

| Metric | Count |
|---|---:|
| artifacts inventoried | 260 |
| real local saved reports | 259 |
| synthetic fixtures | 1 |
| skipped too large | 1 |
| rows evaluated | 11,441 |
| rows skipped by row bound | 2,034 |

## Findings

| Metric | Count |
|---|---:|
| near-certain economic rows | 472 |
| later-win rows | 9,268 |
| weak-history rows | 1,708 |
| weak-history near-certain later-win rows | 10 |
| real weak-history near-certain later-win rows | 8 |
| sufficient real rows for local blocker closure | 8 |
| unknown weak-history rows | 9,733 |
| unknown winner-rank rows | 2,173 |

The replay proves that saved reports can be read offline and that Phase 2 economic probability is available for the target pattern. It does not close the remembered weak-history ranking blocker because the sufficient real sample is small and does not prove current live ranking distribution.

## What Remains Blocked

- Bounded live/RPC or newly available stable saved-report rerun for weak economic history near-certain later winners.
- Any scorer tuning, ranking change, Phase 3, gate change, storage change, or UI sorting/filtering change.
- Treating synthetic fixture rows as production evidence.

## Gate

Decision: `weak_history_needs_live_rpc_validation`.
