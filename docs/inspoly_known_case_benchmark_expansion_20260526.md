# InsPoly Known-Case Benchmark Expansion And False-Positive Controls

Date: 2026-05-26

Base commit: `f2c8547` - `Consolidate strategic control layer`

Runtime changed: `false`

Network/RPC used: `false`

Push/PR performed: `false`

Gate decision: `known_case_benchmark_expanded`

## Strategic Campaign Brief Summary

The release candidate is verified, and runtime/model workstreams are either stable or explicitly blocked. The next highest-leverage local workstream is validation depth: expand the known-case benchmark with false-positive and overclaiming controls without touching production scoring, gates, storage, UI sorting/filtering, Phase 3 runtime, pagination, or replay persistence.

The selected path was to extend the existing offline known-case corpus and runner contract. The campaign did not import bulky raw reports or review packets; it copied only compact case metadata and source notes into the fixture.

## Current Benchmark Recovery

Before this campaign:

- Corpus: `tests/fixtures/known_case_benchmark/post_side_outcome_known_cases.json`
- Schema: `known_case_benchmark_v1`
- Cases: `16`
- Required categories covered: `16`
- False-positive control cases: `0`
- Advisory sidecar context cases: `0`
- Gate: `known_case_corpus_ready`

The existing benchmark covered Side/Outcome Phase 2/4 behavior, old-report fallback, malformed fallback, sensitive overlap, Phase 3 blocked overlap, scanner/archive/Event Forensic affected rows, and a stable unaffected control.

## Expansion Summary

After this campaign:

- Schema: `known_case_benchmark_v2`
- Cases: `24`
- Required categories covered: `24`
- Missing categories: `0`
- False-positive control cases: `4`
- Advisory sidecar context cases: `4`
- Synthetic cases remain: `7`
- Real or derived local cases: `17`

New categories:

- `true_low_probability_later_winner`
- `weak_history_near_certainty_demotion`
- `selected_market_vs_whole_event_scope_boundary`
- `pagination_truncation_warning_control`
- `false_positive_near_certainty_control`
- `high_volume_public_user_false_positive_control`
- `funding_unknown_control`
- `no_independent_hard_evidence_control`

## Source Inventory

| Source | Used for | Commit policy |
|---|---|---|
| `false_positive_library/false_positive_pattern_library_20260505_151140.json` | near-certainty, high-volume public-user, funding-unknown, no-independent-hard-evidence controls | local-only source; compact fixture references only |
| `validation_outputs/event_forensic_weak_history_policy_evidence_20260524.json` | true low-probability later-winner and weak-history near-certainty demotion context | local sidecar evidence; compact fixture references only |
| `validation_outputs/event_forensic_scope_semantics_audit_20260525.json` | selected-market vs whole-event scope boundary | compact committed validation output |
| `validation_outputs/event_forensic_pagination_impact_assessment_20260526.json` | pagination/truncation warning control | compact committed validation output |
| existing Side/Outcome review packets and audits | preserved original 16 cases | local/generated source references only |

Deferred or rejected:

- Raw Event Forensic reports: too bulky/noisy for direct fixture import.
- Full review packet directories: local-only generated artifacts; not staged.
- Live/RPC refresh: unnecessary for this local fixture/control expansion.
- Exact-wallet claims from public-case material without sufficient source proof: deferred to future human curation.

## Schema And Runner Changes

`known_case_benchmark_v2` adds compact advisory fields:

- `assertion_type`
- `expected_behavior`
- `forbidden_interpretation`
- `false_positive_notes`
- `source_note`

The runner now verifies that advisory and false-positive controls remain conservative:

- `automatic_action_allowed` must be `false`.
- `safe_to_use_for_scoring_claims` must be `false`.
- false-positive controls require `false_positive_control: true`.
- advisory controls require fresh validation before any model use.
- direct gate mutation and Phase 3 runtime remain forbidden.

The unified benchmark registry now includes `false_positive_controls` as an explicit required category, still sourced from the fixture corpus.

## What This Proves

The expanded benchmark proves that local regression checks can detect accidental weakening of:

- BUY/SELL YES/NO economic probability semantics;
- cluster-direction normalization;
- malformed and old-report fallback behavior;
- Phase 3 blocked/runtime-forbidden expectations;
- false-positive advisory-only boundaries;
- weak-history near-certainty and selected-market scope overclaiming boundaries;
- pagination/truncation monitor-only interpretation.

## What This Does Not Prove

This benchmark does not prove:

- live recall on fresh Polymarket data;
- exact-wallet public insider case truth;
- Phase 3 runtime readiness;
- production pagination completeness;
- report/storage/browser schema migration safety;
- scoring weight, threshold, gate, or candidate-admission correctness.

## Gate Decision

Gate: `known_case_benchmark_expanded`.

The corpus is now stronger for future local validation and false-positive control. It remains sidecar-only and is not a scorer tuning dataset.

## Verification

- `py_compile` passed for changed benchmark tools/tests.
- Known-case and unified benchmark tests passed `17` tests.
- Benchmark schema compatibility tests passed as part of a `31` test benchmark/schema group.
- Side/Outcome, Event Forensic scope/weak-history, cross-mode, and scanner focused suites passed `235` tests.
- Phase 3/review/autonomous guardrail focused suites passed `92` tests.
- Full unittest discovery passed `1109` tests with existing sqlite `ResourceWarning` noise and the known validation-interrupted terminal artifact message.
- JSON validation passed for the expansion summary and benchmark run outputs.
- Direct diff scans found no protected `app/` runtime diff.

## Next Allowed Benchmark Work

The next safe benchmark campaign is human-curated public-case labeling:

- distinguish exact-wallet assertions from pattern-level assertions;
- require source URLs/timestamps and final human labels;
- keep draft-assisted labels out of executable scoring claims;
- add cases only when provenance is strong enough.
