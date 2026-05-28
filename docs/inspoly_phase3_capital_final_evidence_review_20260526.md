# InsPoly Phase 3 Capital-at-Risk Final Evidence Review

- Date: 2026-05-26
- Scope: final evidence review and runtime readiness decision
- Runtime implementation authorized: `false`
- Network/RPC used: `false`
- Gate decision: `phase3_sidecar_only_final`
- Runtime blocker state: `phase3_blocked_until_new_source_fields`

## Executive Summary

Phase 3 capital-at-risk has enough evidence for sidecar-only accounting review, but not enough evidence for production runtime migration.

The formula is no longer the main blocker for rows with direct fields: BUY exposure can use observed cash or `size * price`, and SELL max loss can be computed as `size * (1 - raw_token_price)` when side, outcome, size, and raw token price are direct and auditable. The blocker is source quality and sensitive overlap. Old saved reports and display-only rows still cannot be reinterpreted as economic max-loss evidence, no local source exposes an explicit collateral/max-loss field, and the sensitive-overlap sample did not produce safe real SELL evidence.

No runtime RFC was created in this campaign. Runtime Phase 3 remains blocked until new source fields or stronger real artifact evidence close the sensitive-overlap and old-report fallback gaps.

## Evidence Reviewed

| Source | Gate / status | Key evidence |
|---|---|---|
| Initial Phase 3 RFC and audit | `keep_phase3_blocked` | 16,123 records scanned, 3,000 rows with hypothetical capital delta, 2,177 sensitive-overlap rows |
| Source inventory and ledger cross-check | `phase3_ready_for_partial_safe_sidecar_only` | 16,340 rows evaluated, 6,527 safe BUY cash rows, 852 safe SELL max-loss rows, 7,134 old notional-only unsafe rows |
| Real SELL expansion | `phase3_still_sidecar_only_needs_more_real_sell_evidence` | 3,049 SELL rows, 104 real SELL rows, 104 safe real SELL max-loss rows, 0 safe real sensitive SELL rows |
| Ledger cross-check | sidecar proof only | 5 artifact dirs, 8 rows, 1 SELL row, 1 safe SELL complement row |
| Known-case and tests | regression guard | Source classification and unsafe old-report semantics are covered by focused tests |

## Evidence Counts

| Metric | Count |
|---|---:|
| Original records scanned | 16,123 |
| Original evaluable rows | 14,108 |
| Original rows with capital delta | 3,000 |
| Original affected unique trade keys | 1,179 |
| Original sensitive-overlap rows | 2,177 |
| Source inventory rows evaluated | 16,340 |
| Safe BUY cash rows | 6,527 |
| Safe SELL max-loss rows | 852 |
| Real-local safe SELL max-loss rows in source inventory | 848 |
| Display-only safe review rows | 1,796 |
| Old notional-only unsafe rows | 7,134 |
| Unknown/missing-field rows | 31 |
| Runtime-safe candidate rows in sidecar inventory | 2,267 |
| Rows still unsafe in unblock audit | 8,961 |
| Real SELL evidence rows | 104 |
| Safe real SELL max-loss rows | 104 |
| Old saved-report/display-only SELL rows | 2,895 |
| Sensitive safe SELL rows | 0 |

## Source Quality Matrix

| Source | BUY capital safe? | SELL max-loss safe? | Collateral/max-loss proof? | Sensitive-gate safe? | Evidence count | Runtime conclusion |
|---|---|---|---|---|---:|---|
| Live normalized trade rows | Not used in this campaign | Not used in this campaign | Unknown | Unknown | 0 new rows | Requires a separate bounded probe if future evidence is needed |
| Reconstruction artifacts | Yes, when side/outcome/price/size are direct | Yes, formula-derived for direct SELL rows | No explicit collateral field | Not proven for sensitive overlap | 102 safe reconstruction SELL rows | Safe sidecar evidence, insufficient for runtime |
| Profile artifacts | Yes, when direct fields exist | Yes, formula-derived for direct SELL rows | No explicit collateral field | Not proven for sensitive overlap | 2 safe profile SELL rows | Safe sidecar evidence, insufficient for runtime |
| Archive CSV/report rows | Sometimes, when full direct fields exist | Sometimes, only if direct side/outcome/price/size exist | No explicit collateral field | Risky in sensitive contexts | mixed, included in 16,340 inventory rows | Sidecar classification only |
| Old saved reports | No for reinterpretation from notional-only fields | No for reinterpretation from notional-only fields | No | No | 7,134 old notional-only unsafe rows | Must stay no-op/unknown |
| Display-only notional fields | No for runtime capital semantics | No for runtime max loss | No | No | 1,796 display-only rows and 2,895 display-only SELL rows | Analyst context only, not runtime evidence |
| Ledger helper outputs | Yes for observed cash semantics | Yes in tiny direct SELL fixture sample | No explicit collateral field; proves cash/proceeds separation | Not enough sensitive coverage | 8 rows, 1 safe SELL row | Formula/sidecar validation only |

## Sensitive Overlap Deep Audit

The dangerous part of Phase 3 is not whether the formula can be written. It is whether applying it in runtime would silently affect Strong Risk, HER, funding-sensitive, candidate-admission-adjacent, or high-review surfaces.

Current sensitive evidence remains insufficient:

| Sensitive metric | Count / status |
|---|---:|
| Prior affected sensitive-overlap rows | 2,177 |
| Real SELL rows found in latest expansion | 104 |
| Safe real sensitive SELL rows | 0 |
| Sensitive review packets generated | 1 |
| Sensitive packets safe sidecar-only | 0 |
| Sensitive packets needing source fields | 1 |

The latest real SELL expansion found real direct-field SELL evidence, but it did not convert the sensitive-overlap blocker into safe direct evidence. The only packetable sensitive row was not production-grade evidence for runtime migration.

Runtime Phase 3 would still risk:

- giving false confidence to old notional-only rows;
- changing capital-sensitive scoring context without enough source-quality proof;
- affecting funding/HER/Strong Risk-adjacent interpretation;
- making old reports appear more precise than they are.

## Sidecar-Only Feasibility

Sidecar-only capital context is useful and should remain available under strict limits.

Allowed sidecar usage:

- annotate only rows with direct source-quality evidence;
- keep observed cash/proceeds separate from SELL max loss;
- mark old reports and display-only rows as unsafe or unknown;
- generate review packets for analyst inspection;
- keep output outside production scoring, gates, storage migrations, and UI sorting.

Not allowed from current evidence:

- replacing scanner/archive/Event Forensic runtime capital-at-risk;
- changing `_score_trade()` or `_event_forensic_score()`;
- using old `capital_at_risk_usdc`, `positionSize`, or notional-only fields as economic max loss;
- changing Strong Risk/HER/funding/candidate-admission behavior.

## Runtime Readiness Decision

Decision: `phase3_sidecar_only_final`.

Runtime blocker state: `phase3_blocked_until_new_source_fields`.

Why not `phase3_runtime_ready_for_rfc`:

- sensitive-overlap direct evidence is still insufficient;
- `0` safe real sensitive SELL rows were found;
- `7,134` old notional-only rows remain unsafe for reinterpretation;
- `2,895` old saved-report/display-only SELL rows remain unsafe for runtime max-loss semantics;
- no local artifact exposes an explicit collateral/max-loss field;
- ledger cross-check evidence is strong for semantics but too small for production readiness;
- old-report no-op behavior and gate drift would still need stronger proof before runtime migration.

Why not pure `phase3_blocked_until_new_source_fields` as the only conclusion:

- sidecar accounting is useful for direct-field rows;
- the formula and source-quality classifier are stable enough for analyst-only review;
- the existing sidecar tools/tests can continue gathering evidence without changing runtime behavior.

## Conditions That Would Unblock A Runtime RFC

Before creating a runtime migration RFC, a future campaign must provide all of the following:

1. Real/non-synthetic sensitive-overlap SELL rows with direct side, outcome, raw token price, and size.
2. A decision on whether formula-derived SELL max loss is acceptable without an explicit collateral/max-loss field, or a new source field that directly proves collateral/max loss.
3. A before/after sensitive-gate audit proving no accidental Strong Risk, HER, funding, or candidate-admission migration.
4. Old-report tests proving notional-only rows remain no-op/unknown.
5. Separate additive output fields for raw fill notional, observed cash/proceeds, economic max loss, and source-quality status.
6. Product/operator approval for runtime behavior change after the RFC, not before.

## Optional Probe Decision

No new live/RPC probe was run. Existing local evidence is enough to make the runtime readiness decision: sidecar-only remains useful, while runtime Phase 3 remains blocked. A live sample would not resolve old saved-report reinterpretation risk or the lack of safe real sensitive SELL evidence by itself.

## Preserved Invariants

- No Phase 3 runtime implementation.
- No `_score_trade()` or `_event_forensic_score()` Phase 3 edits.
- No scoring weight or threshold changes.
- No Strong Risk, HER, funding, or candidate-admission changes.
- No storage schema changes.
- No UI sorting/filtering changes.
- No saved artifact mutation.
- No live/RPC/network calls.
- No private-key, CLOB auth, trading, or order-placement behavior.
- Funding missing remains `unknown`, not zero.
- Old reports remain backward compatible and absent-safe.

## Next Allowed Action

Continue Phase 3 only as sidecar/source-quality work unless new direct source fields appear. The highest-value next Phase 3 work is a curated search for real sensitive-overlap SELL rows with direct fields, plus an expanded ledger/reconstruction cross-check. Runtime implementation should remain blocked until those conditions are met.
