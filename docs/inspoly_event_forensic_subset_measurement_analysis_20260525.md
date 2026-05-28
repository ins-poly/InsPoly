# Event Forensic Subset Measurement Analysis

Date: 2026-05-25

Gate: `subset_measurement_blocked_scope`

Patch RFC: not created

## Scope

This was an approved subset-only live/RPC measurement for:

- Event: `us-x-iran-permanent-peace-deal-by`
- Source package: `docs/inspoly_event_forensic_subset_measurement_approval_package_20260525.md`
- Selection output: `validation_outputs/event_forensic_subset_measurement_selection_20260525.json`
- Raw validation output directory: `validation_outputs/event_forensic_subset_measurement_20260525_181811/`
- Analysis output: `validation_outputs/event_forensic_subset_measurement_analysis_20260525.json`

The selected subset used 6 explicit market identities from the local saved report family. Current live resolution returned 15 event markets, so this run is not whole-event complete and must not be used as full-event completeness evidence.

## Bounds Used

- Max subset events: 1
- Max subset markets: 8
- Max candidate wallets per market: 150
- Max raw rows: 50,000
- Max wall time: 30 minutes
- Funding traces: disabled
- Storage: isolated validation directory only
- Private keys/CLOB auth/trading/order placement: not used

## Selected Markets

- `us-x-iran-permanent-peace-deal-by-april-22-2026`
- `us-x-iran-permanent-peace-deal-by-april-30-2026-925`
- `us-x-iran-permanent-peace-deal-by-may-31-2026-333-871`
- `us-x-iran-permanent-peace-deal-by-june-30-2026-837`
- `us-x-iran-permanent-peace-deal-by-april-24-2026`
- `us-x-iran-permanent-peace-deal-by-may-15-2026`

Three saved-report slugs mapped by condition ID to current live slugs with additional suffixes. This was recorded as slug drift, not as scope expansion.

## Measurement Result

The analysis completed in the isolated validation directory, but the campaign gate is blocked because the result exceeded the approved candidate-wallet density bound.

| Metric | Value |
|---|---:|
| Live resolved event markets | 15 |
| Selected subset markets | 6 |
| Raw trade rows | 31,919 |
| Candidate rows | 15,353 |
| Candidate wallets | 3,239 |
| Truncated markets | 6 |
| Total seconds | 663.47 |
| Wall clock seconds | 672.31 |
| Dominant bottleneck | `score_candidates_seconds` |

Runtime bound violation:

- `candidate_wallet_count_exceeds_per_market_bound`

Timing breakdown:

- `score_candidates_seconds`: 388.20s
- `prefetch_wallet_context_seconds`: 236.57s
- `collect_event_trades_seconds`: 14.74s
- `prepare_candidate_context_seconds`: 5.31s
- `assemble_report_rows_seconds`: 4.22s
- `total_seconds`: 663.47s

## Interpretation

The subset reproduced the larger-event performance shape that the single-market controls could not show: candidate scoring and wallet-context prefetch dominate once the candidate set becomes large. It also confirmed pagination/truncation concerns inside the subset, because all 6 selected markets hit the trade pagination cap.

However, because the subset exceeded the approved candidate-wallet density bound, this run cannot be treated as a clean completed measurement and is not sufficient to select a runtime patch in this campaign.

## Pagination

Pagination gate: `pagination_issue_observed`

Truncation appeared in 6 of 6 selected markets. This supports keeping pagination work operator-gated and separately scoped. The subset result does not prove full-event pagination correctness because 9 live event markets were excluded by design.

## Patch Decision

No performance patch RFC was created in this campaign.

Reason:

- The measurement exceeded an explicit campaign bound.
- The bottleneck signal is useful but came from a scope-blocked run.
- A safe patch decision would need either a narrower approved subset that stays under candidate-wallet density limits or explicit approval to study this larger candidate density as a performance target.

Likely future RFC target if approval is expanded:

- scorer/candidate-context performance for very large Event Forensic candidate sets;
- wallet-context prefetch budgeting;
- pagination/truncation metadata, not candidate skipping.

## Preserved Invariants

- No scoring weights or thresholds changed.
- No direct Strong Risk/HER/funding/candidate-admission gates changed.
- No Phase 3 capital-at-risk runtime migration was implemented.
- No storage schema changed.
- No UI sorting/filtering changed.
- No saved reports/artifacts were mutated.
- No private keys, CLOB auth, trading, or order placement were used.
- No push or PR was performed.

## Next Step

Gate remains `subset_measurement_blocked_scope`.

Recommended next action: choose one of these explicit approvals before runtime optimization:

1. approve a narrower subset that keeps candidate-wallet density under 150 per market;
2. approve a higher-density performance study for this exact 6-market subset;
3. provide a different larger event/subset target with expected lower candidate-wallet density.
