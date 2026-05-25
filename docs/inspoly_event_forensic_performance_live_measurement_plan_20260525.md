# InsPoly Event Forensic Performance Live Measurement Plan

- Date: 2026-05-25
- Scope: future bounded measurement plan
- Executed in this campaign: `false`
- Network/RPC used in this campaign: `false`

## Why A Future Measurement Is Needed

The local performance inventory gives useful historical evidence, but it cannot prove current runtime cost after recent commits or current upstream API behavior. A fresh bounded measurement is needed before any behavior-preserving optimization patch that changes runtime code.

## Bounds

Future run must stay within:

- max events: `1`
- max markets: `8`
- max wall time: `30 minutes`
- no broad discovery;
- no private keys;
- no CLOB auth;
- no order placement;
- no scorer tuning;
- no gate changes.

## Target Selection

Use one known local Event Forensic report as the target seed:

1. Prefer a completed whole-event report already present under `event_forensic_outputs/`.
2. Prefer an event with known high wallet-context or trade-collection timing.
3. Avoid arbitrary Polymarket search or broad event crawling.

## Required Measurements

Collect only read-only timing and counts:

- `resolve_input_seconds`
- `collect_event_trades_seconds`
- `trade_collection_market_total`
- `trade_collection_raw_trade_rows`
- `trade_collection_truncated_markets`
- `prefetch_wallet_context_seconds`
- `prepare_candidate_context_seconds`
- `prefetch_funding_context_seconds`
- `score_candidates_seconds`
- `assemble_report_rows_seconds`
- `total_seconds`
- candidate count
- wallet-context count
- market count
- truncated-market count

## Stop Conditions

Stop and do not optimize if:

- the run would exceed bounds;
- required read-only config is missing;
- rate limits or auth errors dominate;
- the proposed fix would change candidate admission, scoring, thresholds, gates, storage schema, or UI sorting/filtering.

## Output Location

Future measurement output should go under:

`validation_outputs/event_forensic_performance_measurement_YYYYMMDD_HHMMSS/`

Do not overwrite prior outputs.

## Gate

This plan supports a future `needs_live_performance_measurement` gate. It does not authorize a live run by itself.
