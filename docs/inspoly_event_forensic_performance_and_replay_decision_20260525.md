# InsPoly Event Forensic Performance And Replay Decision

- Date: 2026-05-25
- Runtime optimization implemented: `false`
- Replay snapshot sidecar implemented: `true`
- Network/RPC used: `false`
- Storage schema migration: `false`
- Decision gate: `replay_snapshot_sidecar_ready`

## Current Behavior

Event Forensic already records stage timings in report `performance` and writes a runtime profile file into report bundles. Whole-event runs may still be expensive because event-wide trade collection and wallet-context loading can scale with market count, trade count, and wallet count.

Recent scope semantics are explicit: selected-market reports remain selected-market primary scoring, while whole-event reports are explicit whole-event scope. This campaign does not change that behavior.

## What Was Added

- `tools/event_forensic_performance_inventory.py`
  - read-only local saved-report performance inventory;
  - skips raw event bundles;
  - classifies selected-market vs whole-event runs;
  - extracts stage timing and count fields;
  - writes `validation_outputs/event_forensic_performance_inventory_20260525.json`.

- `app/event_forensic_replay.py`
  - pure replay snapshot helper;
  - builds snapshot payloads from already-collected report/candidate rows;
  - preserves scope, timing, candidate ids, winner metadata, and score-input metadata;
  - never runs analysis, fetches data, writes storage, or changes scores.

- `tests/test_event_forensic_performance_inventory.py`
- `tests/test_event_forensic_replay_snapshot.py`
- Contract and decision docs.

## Inventory Findings

From `validation_outputs/event_forensic_performance_inventory_20260525.json`:

| Metric | Count |
|---|---:|
| reports loaded | 154 |
| selected-market runs | 123 |
| whole-event runs | 24 |
| unknown-scope runs | 7 |
| runs with truncated markets | 131 |
| max analysis-market count | 97 |
| max candidate trade count | 10,706 |
| max wallet context count | 2,726 |
| slowest total seconds | 3,606.12 |
| slowest whole-event seconds | 1,572.28 |

Dominant stage counts:

| Stage | Runs |
|---|---:|
| `collect_event_trades_seconds` | 86 |
| `prefetch_wallet_context_seconds` | 45 |
| `prefetch_funding_context_seconds` | 13 |
| `score_candidates_seconds` | 2 |
| `unknown` | 8 |

## Optimization Decision

No runtime performance optimization was implemented.

Reason:

- local saved outputs are strong enough to identify broad bottleneck families, but not enough to prove a current-code optimization;
- some slow saved reports predate recent changes;
- stage dominance varies by run;
- safe optimization requires fresh bounded before/after timing on current code.

Decision for performance work: `needs_live_performance_measurement` before runtime patch.

## Replay Decision

Replay snapshot sidecar is safe and useful now.

Decision for replay work: `replay_snapshot_sidecar_ready`.

The helper is intentionally sidecar-only. It does not authorize:

- replay table/storage migration;
- automatic snapshot writes during runtime analysis;
- live rerun scheduling;
- candidate admission changes;
- scoring or ranking changes.

## Regression Boundaries

Preserved:

- scoring weights;
- thresholds;
- Strong Risk/HER/funding/candidate-admission gates;
- Side/Outcome semantics;
- Phase 3 capital-at-risk blocker;
- storage schema;
- UI sorting/filtering;
- saved report compatibility;
- private-key/CLOB-auth/trading prohibitions.

## Next Safe Step

Use the replay snapshot helper in a sidecar-only validation campaign against representative saved reports. For runtime optimization, run the bounded measurement plan first and only then consider a behavior-preserving patch.

## Rollback

Revert:

- `tools/event_forensic_performance_inventory.py`
- `app/event_forensic_replay.py`
- `tests/test_event_forensic_performance_inventory.py`
- `tests/test_event_forensic_replay_snapshot.py`
- `docs/inspoly_event_forensic_whole_event_performance_inventory_20260525.md`
- `docs/inspoly_event_forensic_replay_persistence_contract_20260525.md`
- `docs/inspoly_event_forensic_performance_live_measurement_plan_20260525.md`
- this decision doc
- `validation_outputs/event_forensic_performance_inventory_20260525.json`

No runtime data or storage rollback is needed.
