# InsPoly Phase 3 Real SELL Evidence Expansion

- Date: 2026-05-25
- Scope: sidecar-only real evidence expansion for Side/Outcome Phase 3 capital-at-risk
- Runtime implementation authorized: `false`
- Network/RPC used: `false`
- Gate decision: `phase3_still_sidecar_only_needs_more_real_sell_evidence`

## Inputs

- `docs/inspoly_phase3_capital_unblock_decision_20260525.md`
- `docs/inspoly_phase3_capital_at_risk_formula_contract_20260525.md`
- `validation_outputs/phase3_capital_source_inventory_20260525.json`
- `validation_outputs/phase3_capital_ledger_crosscheck_20260525.json`
- `validation_outputs/phase3_capital_unblock_impact_audit_20260525.json`
- `tools/phase3_capital_source_inventory.py`
- `tools/phase3_capital_ledger_crosscheck.py`
- `tools/phase3_capital_unblock_impact_audit.py`
- `app/polymarket_ledger.py`
- `app/side_outcome.py`

## New Outputs

- `tools/phase3_real_sell_evidence_discovery.py`
- `tools/phase3_sensitive_capital_review_packets.py`
- `validation_outputs/phase3_real_sell_evidence_discovery_20260525.json`
- `phase3_capital_review_packets/phase3_sensitive_overlap_20260525/`
- `tests/test_phase3_real_sell_evidence_expansion.py`

## What This Campaign Tested

The previous unblock decision allowed partial sidecar-only capital/accounting work but kept production Phase 3 blocked. This campaign expanded the real local evidence search for SELL rows, with emphasis on rows where SELL max loss can be computed from direct side/outcome/price/size fields.

The new tools are read-only and sidecar-only. They do not import scanner/archive/Event Forensic runtime paths, do not perform network calls, and do not mutate saved reports or source artifacts.

## Real SELL Evidence Discovery

From `validation_outputs/phase3_real_sell_evidence_discovery_20260525.json`:

| Metric | Count |
|---|---:|
| records evaluated | 16,415 |
| SELL rows | 3,049 |
| real SELL rows | 104 |
| safe SELL max-loss rows | 905 |
| safe real SELL max-loss rows | 104 |
| safe reconstruction SELL rows | 102 |
| safe profile SELL rows | 2 |
| existing fixture SELL rows | 14 |
| synthetic SELL rows | 33 |
| generated-audit SELL rows | 3 |
| old saved-report/display-only SELL rows | 2,895 |
| sensitive overlap rows surfaced for packets | 1 |
| sensitive safe SELL rows | 0 |

Source provenance counts:

| Source provenance | SELL rows |
|---|---:|
| `real_local_reconstruction` | 102 |
| `real_local_profile` | 2 |
| `existing_fixture` | 14 |
| `synthetic_fixture` | 33 |
| `generated_audit` | 3 |
| `old_saved_report_display_only` | 2,895 |

Source-quality counts:

| Source quality | SELL rows |
|---|---:|
| `safe_for_sell_max_loss` | 905 |
| `safe_for_display_only` | 1,796 |
| `unsafe_old_notional_only` | 330 |
| `unknown_missing_fields` | 18 |

## Sensitive-Overlap Review Packets

Output directory: `phase3_capital_review_packets/phase3_sensitive_overlap_20260525/`

| Metric | Count |
|---|---:|
| packets generated | 1 |
| safe sidecar-only packets | 0 |
| unsafe old-notional packets | 0 |
| packets needing source fields | 1 |

The only packetable sensitive row in this discovery output is a synthetic fixture/display-only case. It is useful as a schema guardrail, but it is not production evidence for runtime Phase 3.

The older Phase 3 impact audit still reports `2,177` sensitive-overlap rows. This campaign did not convert those into direct real normalized trade evidence with sufficient side/outcome/price/size fields.

## What Improved

- Real local normalized SELL evidence increased to `104` rows with direct fields sufficient for sidecar SELL max-loss calculation.
- The evidence split now clearly distinguishes real local reconstruction/profile rows from generated audit evidence, existing fixtures, synthetic fixtures, and old display-only rows.
- The packet generator gives a stable review format for future sensitive-overlap rows once stronger real evidence is available.
- The discovery tool now keeps amount-like fields as plain decimals while preserving percent-tolerant parsing only for price fields.

## What Remains Unsafe

- `2,895` SELL rows remain old saved-report/display-only rows in the current discovery output.
- The previous source inventory still has `7,134` old notional-only unsafe rows.
- No local source exposes an explicit collateral/max-loss field.
- SELL max loss is still formula-derived from direct trade fields, not independently verified collateral.
- The sensitive-overlap sample did not improve enough: `0` safe real sensitive SELL packet rows were found.
- Old reports must remain no-op/unknown for Phase 3 capital semantics unless direct fields are available.

## Runtime Readiness

This campaign improves sidecar evidence but does not justify a production runtime RFC.

Runtime remains blocked because the strongest new evidence is real but narrow, while the most dangerous area, sensitive overlap, still lacks direct real normalized trade rows. A runtime migration would risk giving false confidence to old notional-only rows and could affect funding/HER/Strong Risk-style contexts without enough source-quality proof.

## Requirements To Reconsider Runtime RFC

Before moving beyond sidecar-only:

1. Find real/non-synthetic sensitive-overlap SELL rows with direct side/outcome/price/size fields.
2. Prove old saved-report/display-only rows stay no-op/unknown in production paths.
3. Expand ledger cross-check coverage beyond the current small sample.
4. Decide whether formula-derived SELL max loss is acceptable without explicit collateral/max-loss fields.
5. Add before/after audits showing no unexpected gate drift.
6. Keep Phase 3 independent from Phase 2 model probability and Phase 4 cluster direction semantics.

## Gate Decision

Decision: `phase3_still_sidecar_only_needs_more_real_sell_evidence`.

Why not `phase3_ready_for_runtime_rfc_after_more_review`:

- safe real SELL rows exist, but sensitive-overlap real evidence is still not sufficient;
- old display-only and old notional-only rows remain numerous;
- no explicit collateral/max-loss source field is available;
- a runtime RFC would still need stronger old-report no-op and sensitive-context guardrails.

Why not `phase3_keep_blocked_accounting_ambiguous`:

- direct side/outcome/price/size rows are no longer accounting-ambiguous for sidecar max-loss review;
- the remaining blocker is source coverage and sensitive overlap, not the formula itself.

## Explicit Non-Authorization

This report does not authorize:

- Phase 3 runtime capital normalization;
- `_score_trade()` or `_event_forensic_score()` capital changes;
- scoring weight or threshold changes;
- Strong Risk/HER/funding/candidate admission changes;
- storage schema changes;
- live/RPC/network collection;
- saved artifact mutation;
- UI sorting/filtering changes.
