# Indexer Per-Target Collection Policy - 2026-05-27

## Decision

Gate: `per_target_collection_policy_selected_sidecar_only`.

The bounded live indexer runner should add an explicit per-target public-trade cap for multi-target runs, while keeping the existing aggregate `maxRows` limit as a total safety guard. This is the smallest sidecar-only policy that prevents silent target starvation without changing the SQLite schema or any production runtime path.

## Current Problem

The current runner resolves all approved market slugs, then queries public trades once with a comma-separated condition filter. With `maxPages=2` and a 100-row page size, the effective public-trade cap is 200 rows for the whole run. In the latest repeat2 run, all 200 rows landed on the Khamenei target and the Russia/Maduro targets received 0 trade rows.

That result is stable and storage-safe, but not representative enough for warehouse RFC readiness.

## Strategies Considered

| Strategy | Benefit | Risk | Decision |
| --- | --- | --- | --- |
| Current aggregate cap | Preserves existing behavior and repeat evidence. | Can silently starve earlier or quieter targets. | Keep as fallback for old configs only. |
| Per-target cap | Simple, explicit, sidecar-only, and prevents one active target from consuming all rows. | Requires separate public-trade calls per resolved condition. | Select for this campaign. |
| Per-condition cap | Closest to provider identity and warehouse design. | Similar to per-target here, but future multi-condition event targets need more policy work. | Record condition metadata, but do not require schema changes. |
| Round-robin page collection | Could balance pages across active targets. | More complex, harder to validate, and unnecessary before proving per-target calls. | Defer. |
| Minimum-row floor then remaining budget | Useful for long runs with many active targets. | Requires dynamic budget logic and can overfit this three-target probe. | Defer. |
| Config-only warning | Very low implementation risk. | Already done and does not solve the blocker. | Insufficient. |

## Selected Policy

For multi-target configs that include `limits.maxPublicTradesPerTarget`:

- resolve targets exactly as before;
- store market rows exactly as before;
- fetch public trades one condition at a time;
- cap each target at `maxPublicTradesPerTarget`;
- keep `limits.maxRows` as the total run-level safety bound after market rows;
- keep old aggregate collection if the new field is omitted;
- emit summary metadata showing the policy, caps, rows by target, and warnings.

The selected policy does not add per-condition cursor rows in SQLite. Cursor identity remains aggregate for this campaign; per-condition cursor design is deferred to a future warehouse RFC.

## Required Runner Metadata

Future run summaries must include:

- `collectionPolicy`
- `perTargetPublicTradeLimit`
- `aggregatePublicTradeLimit`
- `rowsByTarget`
- `targetStarvationWarnings`
- `capExhaustionWarnings`
- skipped and failed target reasons

The existing `summary.publicTradeCollection` block is the correct location for this metadata.

## Compatibility

Old configs remain valid. If `maxPublicTradesPerTarget` is omitted, the runner must use the prior aggregate collection mode and emit an underrepresentation warning when relevant.

The config validator should reject unsafe per-target cap combinations, especially caps that can exceed the aggregate `maxRows` budget for the configured target count.

## Boundaries

This policy is sidecar-runner-only. It does not authorize:

- warehouse implementation;
- production runtime imports;
- report/browser integration;
- storage schema migration;
- saved report mutation;
- scoring/gate/funding/Phase 3 changes;
- background workers or schedulers;
- CLOB auth, private keys, trading, or order placement.

## Expected Proof

The campaign should prove:

- the hardened config validates before live network use;
- no old single-target config breaks;
- mocked multi-target runs distribute rows under the per-target cap;
- aggregate `maxRows` still limits total rows;
- target failures do not consume another target's cap;
- the approved live run records honest rows-by-target evidence.

If the provider does not honor single-condition public-trade filtering, the campaign must stop at `indexer_collection_hardening_blocked_by_provider_shape`.
