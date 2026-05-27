# Indexer Warehouse W3 Query Run - 2026-05-27

## Scope

Command: `tools/indexer_warehouse_query.py`

Input registry:

- `validation_outputs/inspoly_indexer_warehouse_registry_20260527.json`

Query mode used for the committed run:

- `aggregate`

The tool reads compact W2 registry JSON only. It does not read raw DBs, call live providers, mutate registry files, mutate saved reports, or integrate with production runtime paths.

## What An Analyst Can Learn

The current registry represents:

- runs: 3
- active review candidates: 1
- retained references: 2
- cleanup candidates: 0
- blocked W0/W1 candidates: 0
- markets: 5
- public trade rows: 580
- cursor rows: 6
- malformed raw JSON rows: 0
- duplicate indicators: 0

The current active review candidate is `per_target_multitarget`, backed by the local-only DB path:

- `.inspoly_indexer/bounded_live_multitarget_per_target_20260527/indexer.sqlite3`

## Target Coverage

Target-level coverage is available only for the active per-target run:

| Target | Rows |
| --- | ---: |
| `russia-x-ukraine-ceasefire-by-january-31-2026` | 60 |
| `maduro-in-us-custody-by-january-31` | 60 |
| `khamenei-out-as-supreme-leader-of-iran-by-february-28` | 60 |

The retained first one-target and same-slug repeat references do not include `rowsByTarget` metadata, so W3 does not infer target-level distribution for those runs.

## Health And Retention

Health:

- W0-ready runs: 3
- W1 gate distribution: `ready_for_local_warehouse_review` for all 3
- Malformed raw JSON: 0
- Duplicate indicators: 0
- Health status: `ready_with_stale_historical_warning`

Retention:

- Active review candidate: 1
- Retained references: 2
- Manual cleanup only: true
- Artifact deletion performed: false

The stale-data warning is expected because the registry is historical and does not perform live refresh.

## What Remains Unavailable

Without separate approval, W3 cannot provide:

- live refreshed rows;
- raw DB query details beyond compact registry metadata;
- scoring or ranking;
- insider verdicts;
- funding conclusions;
- report/browser embedded metrics;
- trading/order/private/auth data.

## Why This Is Not A Scoring Or Report Signal

The output explicitly marks `advisory_only`, `sidecar_only`, `not_scoring_signal`, and `not_report_integrated`. It is a local evidence-navigation aid, not a production report field or model input.
