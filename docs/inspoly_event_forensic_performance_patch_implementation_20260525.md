# Event Forensic Performance Patch Implementation - 2026-05-25

## Gate

`behavior_preserving_performance_patch_implemented`

## Patch Scope

Implemented the RFC-approved first patch option: scorer input/context memoization plus additive timing metadata.

Changed runtime surface:

- `app/event_forensic.py`
  - precomputes score-loop lookup maps for wallet-window trades, market notional samples, and domain notional samples;
  - captures one funding resolver health snapshot before candidate scoring;
  - passes the same semantic inputs to `_score_trade()` in the same candidate order;
  - adds additive `performance.score_input_memoization` and `performance.score_candidates_per_second` metadata.
- `app/event_forensic_performance.py`
  - adds pure score-loop memoization metadata helper.

No changes were made to `_score_trade()`, `_event_forensic_score()`, score weights, thresholds, candidate admission, review routing, exports, storage schema, Phase 3 capital-at-risk, or UI sorting/filtering.

## Behavior Invariants

Required invariants:

- candidate IDs unchanged;
- candidate admission unchanged;
- score values unchanged;
- rank order unchanged;
- review bucket unchanged;
- weak-history near-certainty review demotion unchanged;
- export row count unchanged;
- missing-data fallback unchanged.

The patch preserves the existing candidate loop order and keeps the scoring formula untouched. The only runtime reuse is for pure lookup inputs that were already derived before scoring.

## Evidence

Created offline behavior snapshot tooling:

- `tools/event_forensic_behavior_snapshot.py`
- `validation_outputs/event_forensic_behavior_baseline_snapshot_20260525.json`
- `validation_outputs/event_forensic_performance_patch_equivalence_20260525.json`

Equivalence result:

- source: `validation_outputs/event_forensic_subset_measurement_20260525_181811/live_run/event_forensic_outputs/event_forensic_20260525_151815/candidate_trades.json`
- candidate rows checked: 15,353
- export rows checked: 15,353
- gate: `event_forensic_performance_patch_equivalence_static_snapshot_passed`

Limitation: the equivalence JSON uses saved candidate export rows and does not rerun live/RPC analysis. Runtime behavior is also covered by focused unit tests and full local test discovery.

## Expected Performance Benefit

Expected improvement is conservative:

- avoids repeated dictionary lookups for wallet windows and notional sample maps inside the scoring loop;
- avoids rebuilding funding resolver health for every candidate row;
- exposes memoization coverage and per-second scoring rate for future measurements.

The RFC evidence showed the high-density subset spent 388.20s in candidate scoring and 236.57s in wallet-context prefetch. This patch targets the scoring-loop overhead without changing forensic semantics. A bounded post-patch measurement is still needed to quantify runtime impact.

## Rollback

Rollback the changes in:

- `app/event_forensic.py`
- `app/event_forensic_performance.py`
- `tools/event_forensic_behavior_snapshot.py`
- `tests/test_event_forensic_performance_equivalence.py`

Rollback condition: any candidate ID, score, rank, review bucket, admission, or export count mismatch in behavior-equivalence checks.

## Remaining Work

- Run a bounded post-patch measurement when operator approval is available.
- Continue pagination operator-plan work separately.
- Keep Phase 3 capital-at-risk runtime normalization blocked.
