# Event Forensic Performance Measurement Expansion

Date: 2026-05-25

Gate: `performance_needs_subset_measurement`

Pagination gate: `pagination_issue_observed`

Machine-readable outputs:

- `validation_outputs/event_forensic_performance_expansion_candidates_20260525.json`
- `validation_outputs/event_forensic_performance_expansion_resolution_20260525.json`
- `validation_outputs/event_forensic_performance_measurement_aggregate_20260525.json`

Raw validation-only output directories:

- `validation_outputs/event_forensic_performance_measurement_SAFE_TARGET_20260525_170511/`
- `validation_outputs/event_forensic_performance_measurement_expansion_20260525_172426_maduro_in_us_custody/`
- `validation_outputs/event_forensic_performance_measurement_expansion_20260525_172510_nba_mavericks_grizzlies/`

## Bounds

- New candidate targets resolved: max 12
- Additional full measurements: max 3
- Markets per measurement: max 8
- Candidate wallets per market: max 150
- Raw trade rows per measurement: max 50,000
- Wall time per measurement: max 30 minutes
- Total campaign live time: max 75 minutes

No broad crawling, private keys, CLOB auth, trading, order placement, storage mutation, saved-artifact mutation, scorer/gate/Phase 3/UI sorting changes, push, or PR were used.

## Candidate Expansion

The expansion tool combined:

- previous target inventory;
- previous live target-resolution output;
- previous safe-target measurement;
- rebuilt local performance inventory.

It proposed 9 candidates:

- Previous safe unmeasured targets: 2
- Saved-local safe targets: 3
- Candidates with truncation markers: 5

## Live Scope Resolution

The resolution pass checked scope metadata only and did not run full analysis.

- Candidates resolved: 9
- Safe targets found: 2
- Unsafe targets: 7

Safe additional targets:

- `maduro-in-us-custody-by-january-31`
- `nba-will-the-mavericks-beat-the-grizzlies-by-more-than-5pt5-points-in-their-december-4-matchup`

Key blocked larger targets:

- `us-x-iran-permanent-peace-deal-by`: 15 live markets, above the 8-market bound.
- `us-strikes-iran-by`: 65 live markets and saved raw rows above bound.
- `who-will-win-dem-nomination-for-nyc-mayor`: 23 live markets, above bound.
- `highest-temperature-in-london-on-april-22-2026`: 11 live markets, above bound.
- `maduro-out-in-2025`: 6 live markets, but saved candidate-wallet density exceeds the campaign bound.

## Measurements

| Event | Markets | Raw Rows | Candidate Rows | Candidate Wallets | Total Seconds | Dominant Bottleneck | Truncated Markets |
|---|---:|---:|---:|---:|---:|---|---:|
| `russia-x-ukraine-ceasefire-by-january-31-2026` | 1 | 3,208 | 144 | 83 | 20.54 | `collect_event_trades_seconds` | 1 |
| `maduro-in-us-custody-by-january-31` | 1 | 2,517 | 158 | 102 | 22.44 | `prefetch_wallet_context_seconds` | 0 |
| `nba-will-the-mavericks-beat-the-grizzlies-by-more-than-5pt5-points-in-their-december-4-matchup` | 1 | 0 | 0 | 0 | 0.68 | `collect_event_trades_seconds` | 0 |

Aggregate:

- Completed measurements: 3
- Total markets: 3
- Total raw rows: 5,725
- Total candidate rows: 302
- Total candidate wallets: 185
- Median runtime: 20.54 seconds
- Slowest runtime: 22.44 seconds
- Bottleneck counts: `collect_event_trades_seconds` 2, `prefetch_wallet_context_seconds` 1
- Truncation occurrences: 1

## Interpretation

The completed evidence is safe and bounded, but all successful measurements are single-market events. It confirms that the measurement tool can run within bounds and that both trade collection and wallet-context prefetch can dominate at small scale.

It does not prove which behavior-preserving patch would help larger whole-event runs. Larger saved/local examples either currently resolve above the 8-market cap or exceed saved candidate-wallet/raw-row bounds.

## Gates

- Performance gate: `performance_needs_subset_measurement`
- Pagination gate: `pagination_issue_observed`
- Patch decision: no runtime patch or patch RFC yet
- Subset approval: required for larger-event evidence

## Preserved Invariants

- No scorer weights or thresholds changed.
- No direct Strong Risk/HER/funding/candidate-admission gates changed.
- No Phase 3 runtime migration was performed.
- No storage schema changed.
- No UI sorting/filtering changed.
- No saved reports were mutated.
- No private keys, CLOB auth, trading, or order placement were used.
