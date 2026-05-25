# InsPoly Post-Side/Outcome Benchmark Validation

- Date: 2026-05-22
- Scope: offline benchmark/model-quality validation after Phase 2/4 runtime stabilization
- Replay output: `validation_outputs/post_side_outcome_benchmark_replay_20260522.json`
- Inventory output: `validation_outputs/post_side_outcome_benchmark_corpus_inventory_20260522.json`
- Runtime code changed by this validation: false
- Network/RPC used: false
- Gate decision: `post_side_outcome_needs_live_rpc_validation`

## Corpus Inventory Summary

- Total inventory items: `20,481`.
- Real local artifacts: `19,188`.
- Existing fixtures: `53`.
- Synthetic fixtures: `7`.
- Generated audit outputs: `74`.
- Incomplete/local-only items: `1,159`.
- Usable-with-caveats items: `16,592`.
- Unsafe-for-model-conclusions items: `3,808`.

## Replay Counts

The offline replay evaluated `8,686` local rows across `3,138` unique trade keys.

| Metric | Count |
|---|---:|
| records loaded | 8,686 |
| records evaluated | 8,686 |
| unique trade keys | 3,138 |
| artifacts selected | 272 |
| skipped artifacts | 23 |
| generated audit outputs parsed | 9 |
| missing/malformed rows | 4,385 |
| unknown economic probability rows | 1,779 |

## Affected Vs Stable Rows

| Surface | Rows | Unique trade keys |
|---|---:|---:|
| Phase 2 model-relevant changes | 1,807 | 675 |
| Phase 2 low-probability changes | 1,753 | n/a |
| Phase 2 near-certainty changes | 1,339 | n/a |
| Event Forensic later-correctness changes | 68 | n/a |
| Phase 4 direction changes | 1,807 | 675 |
| Phase 3 blocked capital-at-risk overlap | 6,962 | 2,684 |
| Sensitive gate-context overlap | 6,819 | 2,573 |

The row-level replay does not recompute complete merge groups; Phase 4 stabilization remains the source for merge-group counts (`8,045` merge-group rows in the bounded Phase 4 drift audit).

## Expected Vs Unexpected Behavior

Expected:

- SELL YES / SELL NO rows can move from raw-token low-probability interpretation to economic-side high-probability interpretation.
- BUY/SELL expressions that are economically equivalent can now share normalized cluster direction.
- Sensitive contexts overlap changed semantics because Strong Risk/HER/funding/candidate narratives consume existing model flags and cluster evidence.
- Phase 3 capital-at-risk remains blocked even when rows overlap changed Phase 2/4 semantics.

Unexpected:

- Unexpected drift rows: `0`.
- Runtime bug found: `false`.
- Source scans did not detect Phase 3 capital helper use of side/outcome normalization.
- Source scans did not detect storage schema, Polymarket/live, or browser cluster sort/filter changes.

## Known Fragile Area Status

### 1. Event Forensic weak economic history / near-certain later wins

Status: `needs_live_rpc_validation`.

Phase 2 makes near-certainty and later-correctness semantics economic-side aware. The offline replay saw `1,339` near-certainty rows and `68` later-correctness changes, but the remembered weak-history case still requires a live or stable saved report rerun to verify ranking distribution.

No runtime fix was applied in this campaign.

### 2. Event Forensic single-market vs whole-event semantics

Status: `still_architecture_ambiguity`.

Side/Outcome normalization clarifies trade side semantics. It does not change selected-market vs whole-event scope rules, and it should not be used to silently widen single-market reports.

### 3. Archive visibility drift

Status: `monitor_offline`.

Local archive rows are replayable and useful for drift detection. This campaign did not change archive visibility rules. Keep archive visibility drift audit in the local chain and continue treating lossy old archive rows as unsafe for rescoring.

### 4. Funding/HER/Strong Risk sensitive overlap

Status: `expected_indirect_overlap_only`.

The replay found `6,819` sensitive-context rows and `2,573` sensitive unique trade keys. Source scans did not detect direct Strong Risk, HER, funding, or candidate-admission migration. Any future direct gate migration still requires a separate approval gate.

### 5. Browser display compatibility

Status: `covered_by_static_tests`.

UI copy distinguishes Token price from Economic prob. Raw entry-probability sort remains present. This campaign did not change UI sorting/filtering behavior.

## Generated Audit Gates Parsed

| Gate | Count |
|---|---:|
| `phase2_stable` | 1 |
| `phase4_stable` | 1 |
| `keep_phase3_blocked` | 1 |
| `ready_for_phase2_implementation` | 1 |
| `ready_for_phase2_rfc` | 1 |
| `ready_for_phase4_implementation` | 2 |
| `unknown` | 2 |

## Runtime Bug / Fix Status

- Runtime bug found: `false`.
- Fix applied: `false`.
- Reason: local replay and source scans showed expected Phase 2/4 drift only; the remaining strongest validation need is live/saved rerun evidence for remembered fragile Event Forensic cases.

## Gate Decision

Decision: `post_side_outcome_needs_live_rpc_validation`.

This is not a failure of the Phase 2/4 migrations. It means offline corpus validation is clean enough for local regression, but not sufficient to close the remembered live Event Forensic weak-history ranking risk.

## Next Safest Backlog Item

Bounded live or stable saved-report replay for the remembered Event Forensic weak-history near-certainty cases, with explicit operator/RPC approval if live data is needed. Scope must exclude Phase 3, scoring weights/thresholds, direct gates, storage, UI sorting/filtering, and live indexing.
