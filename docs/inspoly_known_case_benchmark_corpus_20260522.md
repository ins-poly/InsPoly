# InsPoly Known-Case Benchmark Corpus

- Date: 2026-05-22
- Scope: stable local Side/Outcome benchmark corpus
- Corpus: `tests/fixtures/known_case_benchmark/post_side_outcome_known_cases.json`
- Run output: `validation_outputs/known_case_benchmark_run_20260522.json`
- Runtime code changed: false
- Network/RPC used: false
- Gate decision: `known_case_corpus_ready`

## Why This Exists

The post-Side/Outcome replay can evaluate thousands of local rows, but it is too noisy for fast future regression checks. This corpus keeps a small stable set of representative cases that can be replayed without live/RPC access.

It does not close the remembered Event Forensic weak-history near-certainty live-validation blocker. It gives future local changes a quick guardrail before any bounded live or saved-report rerun.

## Source Inventory

The curation tool inspected these local source families:

- `validation_outputs/post_side_outcome_benchmark_replay_20260522.json`
- `side_outcome_review_packets/phase2_post_migration_sensitive_cases_20260522/sensitive_cases.json`
- `side_outcome_review_packets/phase4_post_migration_sensitive_merge_groups_20260522/sensitive_merge_groups.json`
- `side_outcome_audits/side_outcome_phase2_archive_evidence_gap_20260522.json`
- `side_outcome_audits/side_outcome_phase2_readiness_impact_audit_20260522.json`
- `side_outcome_audits/side_outcome_phase3_capital_at_risk_audit_20260522.json`

Cases are classified as:

- `real_local_artifact`: selected from bounded replay rows that reference saved local artifacts.
- `generated_audit_evidence`: selected from audit JSON outputs derived from bounded local artifact scans.
- `review_packet`: selected from prior Phase 2/4 review packets.
- `synthetic_fixture`: explicitly generated contract rows for missing or canonical edge cases.

Synthetic cases are never presented as production evidence.

## Corpus Size And Provenance

| Metric | Count |
|---|---:|
| total cases | 16 |
| required categories covered | 16 |
| missing required categories | 0 |
| real local artifact cases | 2 |
| generated audit evidence cases | 3 |
| review packet cases | 4 |
| synthetic fixture cases | 7 |
| real-or-derived local evidence cases | 9 |

Benchmark run result:

| Metric | Count |
|---|---:|
| pass | 15 |
| unknown-pass | 1 |
| fail | 0 |
| Phase 3 blocked cases | 1 |

`unknown-pass` is expected for the malformed fallback case: it passes because it remains `unknown`, not zero or guessed.

## Category Coverage

Covered categories:

- BUY YES unaffected.
- BUY NO unaffected.
- SELL YES low price -> economic NO high probability.
- SELL NO low price -> economic YES high probability.
- SELL YES near-certainty inversion.
- SELL NO near-certainty inversion.
- BUY YES + SELL NO same cluster `long_yes`.
- BUY NO + SELL YES same cluster `long_no`.
- malformed/missing side/outcome fallback.
- old report row without Phase 2/4 additive fields.
- sensitive Strong Risk/HER/funding overlap without direct gate mutation.
- Phase 3 capital-at-risk blocked overlap.
- Event Forensic later-correctness affected case.
- Archive affected case.
- Scanner affected case.
- stable unaffected control case.

## Fragile Cases Covered

Covered locally:

- SELL-side probability inversion after Phase 2.
- normalized cluster grouping after Phase 4.
- Event Forensic later-correctness affected row from local review packet evidence.
- Archive affected row from archive evidence-gap audit.
- sensitive gate-context overlap that must remain indirect only.
- old-report absent-safe derivation from raw side/outcome/price.
- malformed fallback to `unknown`.
- Phase 3 capital-at-risk remains blocked.

## Remaining Uncovered / Live-RPC Needed

Still not closed:

- remembered Event Forensic weak economic history near-certain later-win ranking distribution;
- whole-event vs single-market live distribution on the affected case family;
- any fresh market/wallet state that requires live Data/Gamma/CLOB access.

These remain blocked behind explicit RPC/operator approval or a newly available stable saved-report rerun.

## Sufficiency For Future Local Regression

Decision: this corpus is sufficient for fast local Side/Outcome regression checks. It should be run before future changes that touch:

- `app/side_outcome.py`;
- scanner/archive/Event Forensic Side/Outcome fields;
- Event Forensic later-correctness semantics;
- same-side/cluster grouping;
- old report compatibility for raw side/outcome/price;
- any proposal that claims Phase 3 remains blocked.

It is not sufficient for:

- scoring weight or threshold tuning;
- direct Strong Risk/HER/funding/candidate-admission changes;
- Phase 3 capital-at-risk implementation;
- UI sorting/filtering product decisions;
- live Event Forensic recall validation.

## Gate Decision

Decision: `known_case_corpus_ready`.

Next approval-gated step remains a bounded live/RPC or stable saved-report Event Forensic weak-history near-certainty validation run.

## 2026-05-26 Expansion Addendum

The corpus was expanded to `known_case_benchmark_v2` with `24` compact cases. The original `16` required categories remain covered, and `8` advisory/context categories were added:

- true low-probability later-winner context;
- weak-history near-certainty demotion;
- selected-market vs whole-event scope boundary;
- pagination/truncation warning control;
- false-positive near-certainty control;
- high-volume public-user false-positive control;
- funding-unknown control;
- no independent hard-evidence control.

The expansion adds `4` false-positive library controls and `4` sidecar-context controls. These cases are executable regression guards for overclaiming, not production model labels. They require `automatic_action_allowed: false`, `safe_to_use_for_scoring_claims: false`, and explicit `forbidden_interpretation` text.

Gate remains `known_case_corpus_ready`; the broader campaign gate is `known_case_benchmark_expanded`.
