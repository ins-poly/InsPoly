# Event Forensic Granular Pagination Probe

Date: 2026-05-26

Gate before probe: `pagination_low_impact_monitor_only`

Gate after probe: `granular_probe_no_new_rows_provider_or_query_bound`

## Scope

This was a sidecar-only, one-market live/RPC probe. It did not change production pagination, Event Forensic scoring, candidate admission, ranking, review routing, exports, storage, UI sorting, or saved reports.

Selected event: `us-x-iran-permanent-peace-deal-by`

Selected market: `us-x-iran-permanent-peace-deal-by-april-30-2026-925`

Condition id: `0xceb6dfaa2cf5abc9d47ebc867b984a7715104944249274e8a483a2e17473e5f5`

Selection reason: this was the approved subset market with the highest saved high-review overlap among truncated selected markets. The prior saved report slice had 5,874 baseline rows, 3,100 candidate-floor rows, 92 high-review rows, and 100 weak-history demotion rows.

## Bounds

- Max events: 1
- Max markets: 1
- Max time chunks: 8
- Max pages per window: 31
- Page size: 100
- Max rows per window: 3,100
- Max total unique rows: 50,000
- Max wall time: 30 minutes
- No-new-row plateau stop: 2 pages
- Candidate-floor notional: 250

The live event resolved to 15 markets, but the probe stayed on the single selected market. No whole-event completeness claim is supported.

## Result

Output: `validation_outputs/event_forensic_granular_pagination_probe_20260526.json`

Timestamped sidecar output dir: `validation_outputs/event_forensic_granular_pagination_probe_20260526_131742/`

Summary:

- Baseline rows: 5,874
- Baseline candidate-floor rows: 3,100
- Baseline page requests: 62
- Baseline truncation: true
- Baseline stop reason: `provider_hard_cap_full_last_page`
- Granular rows: 3,593
- Granular candidate-floor rows: 819
- Granular page requests: 60
- Added rows beyond baseline: 0
- Added candidate-floor rows beyond baseline: 0
- Baseline-only rows: 2,281
- Duplicate page count: 0
- Cursor stall count: 0
- No-new-row plateau detected: true
- Provider hard cap detected: true
- Wall clock seconds: 12.23

## Interpretation

The granular time-window probe did not discover any rows outside the current baseline offset slice for the selected high-value market.

The result does not prove the selected market is complete. One active chunk still hit the public offset/page cap, and several quiet chunks ended through no-new-row or older-than-window stops. The best supported conclusion is narrower: under the current bounded one-market, eight-window collection design, truncation behaves like a provider/query-bound condition rather than an immediately recoverable local pagination bug.

This also explains why the earlier 6-market bounded deeper collection did not change row or candidate-floor counts: splitting the same public endpoint into bounded windows did not surface additional unique rows for the tested evidence path.

## Analyst Impact

No sidecar evidence supports a production runtime pagination expansion from this probe:

- No new rows were found.
- No new candidate-floor rows were found.
- No scored candidate replay was performed.
- No rank, review bucket, weak-history demotion, or sensitive-context delta can be claimed.
- Existing truncation warnings and monitoring remain necessary because the public page cap still appears.

## Decision

Gate: `granular_probe_no_new_rows_provider_or_query_bound`

Action:

- Keep production pagination unchanged.
- Keep truncation monitoring/warnings.
- Do not create a production runtime pagination expansion RFC from this evidence alone.
- Future work should focus on provider semantics or a separately approved source/query strategy if deeper completeness is still required.

## Preserved Invariants

- No production pagination expansion.
- No Event Forensic scoring, threshold, gate, candidate-admission, ranking, review-routing, or export change.
- No Phase 3 capital-at-risk runtime implementation.
- No storage schema change.
- No UI sorting/filtering change.
- No saved artifact mutation.
- No private keys, CLOB auth, trading credentials, or order placement.
- No push or PR.
