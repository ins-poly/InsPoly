# InsPoly Phase 3 Capital Source Quality Program

- Date: 2026-05-22
- Scope: Phase 3 capital-at-risk source-quality audit and blocker ledger
- Machine output: `validation_outputs/inspoly_phase3_capital_source_quality_program_20260522.json`
- Runtime implementation in this program: false
- Network/RPC used: false
- Gate decision: `keep_phase3_blocked`

## Current Evidence

The Phase 3 capital-at-risk audit remains the controlling evidence.

| Metric | Count |
|---|---:|
| records scanned | 16,123 |
| evaluable rows | 14,108 |
| rows with capital delta | 3,000 |
| SELL rows with capital delta | 2,991 |
| BUY rows with capital delta | 9 |
| unique trade keys with capital delta | 1,179 |
| sensitive overlap rows | 2,177 |

## Source Quality Findings

- SELL complement max-loss semantics materially differ from raw fill notional.
- `usdcSize` is observed cash/fill value, not automatically verified max-loss collateral.
- Old notional-only rows are unsafe for runtime reinterpretation.
- Funding/HER/Strong Risk-sensitive contexts overlap capital deltas.

## What Remains Blocked

- Runtime capital-at-risk normalization.
- Capital-driven gate or threshold tuning.
- Old-report rescoring from lossy rows.
- Any funding/HER/Strong Risk-sensitive capital migration.

## Allowed Local Work

- Add sidecar-only capital source fixtures.
- Expand source-quality taxonomy.
- Draft a stricter accounting RFC if new evidence appears.

## Approval Required

- Phase 3 runtime implementation.
- Any capital-at-risk field reinterpretation in scanner/archive/Event Forensic.
- Any capital-derived scoring/gate/threshold change.

## Gate Decision

Decision: `keep_phase3_blocked`.

No runtime implementation should proceed until SELL collateral/max-loss and old-report fallback semantics are proven.
