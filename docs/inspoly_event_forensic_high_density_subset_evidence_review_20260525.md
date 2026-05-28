# Event Forensic High-Density Subset Evidence Review

Date: 2026-05-25

Gate: `high_density_subset_evidence_accepted_for_rfc`

## Source Evidence

Source run:

- Commit: `3b97fc7`
- Measurement directory: `validation_outputs/event_forensic_subset_measurement_20260525_181811/`
- Prior report: `docs/inspoly_event_forensic_subset_measurement_analysis_20260525.md`
- Event: `us-x-iran-permanent-peace-deal-by`
- Scope: 6 explicitly selected subset markets out of 15 live event markets

The original run gate was `subset_measurement_blocked_scope` because candidate-wallet density exceeded the previous measurement bound:

- Candidate wallets: 3,239
- Selected markets: 6
- Candidate wallets per selected market: 539.83
- Prior bound: 150 candidate wallets per market

## Reclassification

The approved product/operator decision allows this existing run to be used as high-density subset evidence for RFC analysis only.

This reclassification does not change the original measurement facts:

- The run remains subset-only.
- It is not whole-event complete.
- It does not approve production tuning.
- It does not approve scorer, gate, threshold, storage, Phase 3, or UI sorting changes.

## Why The Evidence Is Useful

The single-market measurements were safe but too small to expose the larger Event Forensic bottleneck shape. This subset run is useful for an RFC because it exercised:

- 31,919 raw rows;
- 15,353 candidate rows;
- 3,239 candidate wallets;
- 6 truncated markets;
- 663.47s total runtime.

Timing decomposition:

| Stage | Seconds | Share of Total |
|---|---:|---:|
| `score_candidates_seconds` | 388.20 | 58.51% |
| `prefetch_wallet_context_seconds` | 236.57 | 35.66% |
| `collect_event_trades_seconds` | 14.74 | 2.22% |
| `prepare_candidate_context_seconds` | 5.31 | 0.80% |
| `assemble_report_rows_seconds` | 4.22 | 0.64% |

Derived costs:

- Score seconds per candidate row: 0.025285
- Wallet-prefetch seconds per candidate wallet: 0.073038
- Candidate rows per wallet: 4.740043
- Candidate rows per market: 2,558.833333
- Repeated wallet/candidate opportunities: 12,114
- Runtime multiple over prior small-target median: 32.301x

## Claims Allowed

- Performance bottleneck evidence for this subset.
- Candidate-density evidence for future RFC design.
- Pagination/truncation was observed within this subset.
- Scoring-loop and wallet-prefetch costs dominate in this high-density subset.

## Claims Not Allowed

- Whole-event completeness.
- Candidate quality conclusions for excluded markets.
- Production scorer tuning approval.
- Scoring weight or threshold changes.
- Candidate admission, Strong Risk, HER, funding, or other gate changes.
- Storage schema or UI sorting changes.

## RFC Consequence

The evidence is sufficient to draft a behavior-preserving performance RFC. It is not sufficient to implement a runtime optimization in this campaign.

The RFC should focus on preserving candidate IDs, score values, rank order, review buckets, candidate admission, and report/export visibility while reducing repeated pure work or improving operator feedback.
