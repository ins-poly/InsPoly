# Indexer Multi-Target Hardening Decision - 2026-05-27

## Decision

Final gate: `indexer_multitarget_hardening_ready_for_repeat_operator_run`.

This is not warehouse approval and not runtime integration approval. It means the target-selection path, resolver preflight, sidecar ingestion, readiness audit, and scoped comparison are now strong enough to justify a future owner-approved repeat run over the same three-target set.

## What Changed In This Campaign

- Added a target/provider failure taxonomy for bounded indexer probes.
- Added a compact target registry rooted in local evidence and prior probe results.
- Added a bounded resolver preflight that checks registry candidates with public read-only resolver calls only.
- Extended the sidecar DB compare tool with scoped market/condition comparison.
- Ran one approved fresh multi-target repeat sidecar ingestion after preflight selected exactly three valid market targets.

No production runtime, scanner/archive/Event Forensic/browser/report/storage schema, scoring, gate, HER, funding, Phase 3, CLOB auth, trading, saved-report, push, or PR behavior changed.

## Target Hardening Result

The failed prior slug `us-x-iran-permanent-peace-deal-by` is now classified as `market_vs_event_ambiguity` plus `target_exceeds_bounds_or_not_single_market`.

Resolver preflight showed:

- `russia-x-ukraine-ceasefire-by-january-31-2026`: valid single market.
- `maduro-in-us-custody-by-january-31`: valid single market.
- `us-x-iran-permanent-peace-deal-by`: rejected as a 15-market event family.
- `khamenei-out-as-supreme-leader-of-iran-by-february-28`: valid single-market replacement.
- NBA sparse fallback: valid single market but not selected because the first replacement worked.

Selected run set:

1. `russia-x-ukraine-ceasefire-by-january-31-2026`
2. `maduro-in-us-custody-by-january-31`
3. `khamenei-out-as-supreme-leader-of-iran-by-february-28`

## Repeat Run Evidence

The fresh local-only DB was written under `.inspoly_indexer/bounded_live_multitarget_repeat_20260527/` and remains unstaged.

Run summary:

- Targets attempted: 3
- Targets completed: 3
- Market rows: 3
- Public trade rows: 200
- Cursor rows: 2
- Malformed raw JSON: 0
- Duplicate indicators: 0
- Readiness gate: `indexer_sidecar_readiness_ready_no_runtime`

Target-level public trade rows were not balanced: the 200 stored trades were all attached to the Khamenei replacement target. The two anchor targets stored market rows but no public trade rows in this run.

## Scoped Compare Result

Scoped compare worked and found no market identity drift, malformed payload drift, duplicate indicators, schema problems, cursor key drift, cursor status drift, or storage-readiness blocker.

It did find provider/collection-sampling drift:

- Previous multi-target anchors vs repeat DB: anchor trade overlap dropped from 200 to 0.
- Same-slug repeat DB vs repeat multi-target DB for Russia: Russia trade overlap dropped from 200 to 0.
- Cursor values changed because the repeat run used a three-condition query and capped public trades at 200 rows.

Classification: `provider_or_collection_sampling_drift_without_storage_identity_drift`.

This is acceptable for a future repeat operator probe, but not for warehouse/runtime/report integration. The next repeat run should either prove the same three-target set is stable or harden collection to fetch per target before any warehouse RFC.

## Answers

- Did target hardening solve the failed slug issue? Yes. The failed Iran slug resolved as a bounded-indexer-invalid event family, and a single-market replacement was selected.
- Is there now a stable 3-target set? Yes for resolver and market metadata; trade distribution still needs repeat evidence.
- Did scoped compare work? Yes.
- Did repeat run pass readiness? Yes.
- Is drift acceptable? Acceptable for a future repeat operator run only; not acceptable for warehouse/runtime integration.
- Is a future operator repeat/more-target run justified? A repeat of the same three targets is justified. More-target expansion is not justified yet.
- Is warehouse/runtime integration still blocked? Yes.

## Next Highest-Leverage Step

Run one future owner-approved repeat over the same three-target set, or first harden public-trade collection to use per-target/per-condition caps so anchor trade evidence is not displaced by the most active replacement target.

Warehouse mode, scheduling, report/UI integration, production imports, and storage schema changes remain blocked.
