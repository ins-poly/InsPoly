# InsPoly Event Forensic Whole-Event Performance Inventory

- Date: 2026-05-25
- Scope: local saved-report performance inventory
- Runtime implementation: `false`
- Network/RPC used: `false`
- Output: `validation_outputs/event_forensic_performance_inventory_20260525.json`
- Gate decision: `performance_local_inventory_ready`

## Current Evidence

The inventory tool scanned bounded local Event Forensic report locations and intentionally skipped raw event bundles. It loaded saved `event_analysis.json` / report JSON files only.

Inventory summary:

| Metric | Count |
|---|---:|
| reports discovered | 158 |
| reports loaded | 154 |
| skipped too large | 4 |
| selected-market runs | 123 |
| whole-event runs | 24 |
| unknown-scope runs | 7 |
| runs with truncated markets | 131 |
| max analysis-market count | 97 |
| max candidate trade count | 10,706 |
| max wallet context count | 2,726 |
| slowest total seconds | 3,606.12 |
| slowest whole-event seconds | 1,572.28 |

Dominant bottleneck counts:

| Dominant bottleneck | Runs |
|---|---:|
| `collect_event_trades_seconds` | 86 |
| `prefetch_wallet_context_seconds` | 45 |
| `prefetch_funding_context_seconds` | 13 |
| `score_candidates_seconds` | 2 |
| `unknown` | 8 |

Timing field maxima:

| Field | Max seconds | Average seconds | Reports with field |
|---|---:|---:|---:|
| `total_seconds` | 3,606.12 | 144.92 | 146 |
| `collect_event_trades_seconds` | 140.28 | 19.40 | 146 |
| `prefetch_wallet_context_seconds` | 363.95 | 18.01 | 146 |
| `prefetch_funding_context_seconds` | 3,575.16 | 89.06 | 146 |
| `score_candidates_seconds` | 1,164.68 | 16.76 | 146 |

## Interpretation

The saved evidence confirms that large Event Forensic runs can still be expensive, but the dominant stage varies:

- many saved runs are trade-collection dominated;
- wallet-context loading remains a major whole-event cost;
- older runs include extreme funding-prefetch stalls;
- historical scorer cost can be high, but recent memory indicates scorer caching already reduced a representative full run to `score_candidates_seconds = 24.60s`.

This means a safe optimization should not guess from one stage. The next runtime optimization should start from a fresh bounded run on current code and compare stage timings before and after.

## What Is Known From Saved Outputs

- Whole-event runs can produce thousands of candidate trades and thousands of wallet contexts.
- Pagination/truncation warnings are common in saved reports.
- Current report schema already persists useful performance fields under `performance`.
- New product-scope metadata is absent in older saved reports, so inventory must infer selected-market vs whole-event from legacy `analysis_scope` when needed.

## What Cannot Be Known Locally

Saved outputs cannot prove current production cost after all recent commits because:

- many reports predate scope metadata, review-demotion, and other later changes;
- live API latency, current pagination behavior, and wallet-history fetch cost can drift;
- skipped large reports may contain additional bottleneck details but are intentionally not parsed in this bounded sidecar scan.

## Behavior-Preserving Optimization Candidates

Potentially safe, but still requiring fresh before/after measurement:

- cache repeated pure per-run lookups that do not affect candidate admission or scores;
- persist replay snapshots from already-collected report data for later comparison;
- add more consistent timing metadata around existing stages;
- avoid re-reading raw bundles in sidecar audits.

## Blocked / High-Risk Optimizations

Do not implement without a separate RFC and explicit approval:

- skipping markets, candidates, wallets, or funding requests for speed;
- changing fetch limits, candidate admission, ranking, thresholds, or gates;
- broadening or narrowing selected-market vs whole-event primary scoring;
- changing storage schema for replay persistence;
- changing UI sorting/filtering behavior;
- Phase 3 capital-at-risk runtime migration.

## Gate Decision

Decision: `performance_local_inventory_ready`.

The local inventory is sufficient to justify replay snapshot sidecar work and a future bounded measurement plan. It is not sufficient to justify runtime performance optimization in this campaign.
