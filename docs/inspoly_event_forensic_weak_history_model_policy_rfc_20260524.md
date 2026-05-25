# InsPoly Event Forensic Weak-History Near-Certainty Model Policy RFC

- Date: 2026-05-24
- Status: RFC-only
- Runtime implementation: not approved
- Network/RPC: not used by this RFC
- Related live evidence: `validation_outputs/event_forensic_weak_history_live_rpc_20260524_112348/summary.json`
- Evidence output: `validation_outputs/event_forensic_weak_history_policy_evidence_20260524.json`
- Simulation output: `validation_outputs/event_forensic_weak_history_policy_simulation_20260524.json`

## Non-Authorization

This RFC is not permission to change Event Forensic runtime behavior.

It does not authorize:

- scoring weight changes;
- threshold changes;
- Strong Risk, HER, funding, or candidate-admission gate changes;
- Phase 3 capital-at-risk work;
- UI sorting/filtering changes;
- storage schema changes;
- live/RPC/network runs;
- report mutation or saved-artifact migration.

Any implementation requires a separate approval gate.

## Problem Statement

The approved bounded live/RPC validation reproduced the remembered pattern:
weak economic-history wallets with near-certain later-winning entries can remain high in the Event Forensic review list.

The live run tested:

| Metric | Count |
|---|---:|
| events | 1 |
| markets | 1 |
| raw trade rows loaded | 3,208 |
| candidate rows | 144 |
| weak-history near-certain later-win rows | 4 |
| high-rank rows among those | 3 |
| missing expected reducer rows | 0 |
| Phase 2 probability mismatches | 0 |
| Phase 4 cluster-direction mismatches | 0 |

The important conclusion is that this is not a narrow runtime bug. The weak-history reducer and near-certainty reducer were present. The ambiguity is policy-level: should these rows remain high when other structural/current-model evidence keeps them in a primary review bucket?

## Evidence Review

### Saved-Report Audit

`validation_outputs/event_forensic_weak_history_saved_report_audit_20260522.json` evaluated 11,441 rows from local saved Event Forensic artifacts. It found:

- 472 near-certain economic rows;
- 1,708 weak-history rows;
- 10 weak-history near-certain later-win rows;
- 8 real weak-history near-certain later-win rows;
- 8 sufficient real rows for local blocker evidence.

The saved-report audit was enough to justify a bounded live/RPC validation, but not enough to close the blocker locally.

### Known-Case Corpus

`tests/fixtures/known_case_benchmark/post_side_outcome_known_cases.json` contains 16 local regression cases. It covers Side/Outcome Phase 2 and Phase 4 semantics, malformed fallback, old-report fallback, sensitive-overlap/no-direct-gate-mutation, Event Forensic later-correctness, archive affected cases, scanner affected cases, and stable controls.

The corpus is useful for local regression, but it is not a labeled model-tuning set.

### Bounded Live/RPC Validation

`docs/inspoly_event_forensic_weak_history_live_rpc_validation_20260524.md` recorded a bounded validation of `russia-x-ukraine-ceasefire-by-january-31-2026`. The run reproduced 4 weak-history near-certain later-win rows. Three appeared at display ranks 7, 8, and 9.

All reproduced rows had:

- economic side/probability available;
- near-certainty reducer evidence;
- weak-history reducer evidence;
- no Phase 2 economic probability mismatch;
- no Phase 4 cluster direction mismatch.

### Current Reducers Present In Code

The current `app/event_forensic.py` policy already includes:

- economic-side probability from `normalize_side_outcome()` inside `_event_forensic_score()`;
- `NEAR_CERTAINTY_PRICE = 0.94` and `VERY_NEAR_CERTAINTY_PRICE = 0.97`;
- later correctness weakening for near-certain entries;
- weak-history reducer via `_poor_wallet_history()`;
- score subtraction for weak history;
- a cap below `EVENT_FORENSIC_PRIMARY_TRADE_THRESHOLD` for weak-history plus near-certainty rows when independent proof is absent;
- summary copy that labels weak-history near-certainty rows as contextual or benign.

The live evidence therefore does not show missing reducer execution. It shows that review placement can still be driven by other review-bucket semantics.

## Current Model Policy Inventory

### Near-Certainty Checks

`_event_forensic_score()` computes `entry_price` from economic-side probability when normalization is available. If economic probability is unknown, it falls back to raw token price. Near certainty is then evaluated against:

- `NEAR_CERTAINTY_PRICE = 0.94`;
- `VERY_NEAR_CERTAINTY_PRICE = 0.97`.

Near-certain later wins receive smaller score additions than lower-probability later wins and add reducer text.

### Weak-History Reducers

Weak history is detected through `_poor_wallet_history(raw)`. Current behavior:

- adds `weak_wallet_track_record`;
- subtracts from Event Forensic score;
- adds reducer copy;
- caps weak-history plus near-certainty cases below primary event-forensic score threshold when independent proof is absent.

This is score-level policy, not a full review-placement override.

### LaterWon / WinnerRank Usage

Event Forensic uses `laterWon` and `winnerRank` as retrospective evidence. Winner ranks add score only when early enough. Near certainty reduces the evidentiary value of later correctness, but does not automatically remove a row from review.

### Review And Ranking Sort Keys

`_event_trade_sort_key()` sorts rows into buckets before considering Event Forensic score:

1. existing `Strong Risk` or retrospective strong;
2. hard-evidence review;
3. event-forensic primary threshold;
4. lower context rows.

This means a row can have low `eventForensicScore` and still remain high if current-model `Strong Risk` or hard-evidence review semantics put it in a higher bucket.

### Economic Probability After Phase 2

Phase 2 is stable. Event Forensic near-certainty and later-correctness semantics use economic-side probability when side/outcome/price normalize safely. The live validation found zero Phase 2 probability mismatches.

### Cluster Direction After Phase 4

Phase 4 is stable. Event Forensic timing clusters carry normalized cluster direction where safe. The live validation found zero Phase 4 cluster-direction mismatches.

### Reducers Affect Score, Placement, And Labels Differently

Current reducers affect:

- `eventForensicScore`;
- `eventForensicReducers`;
- trade summaries;
- candidate audit explanations.

Current reducers do not necessarily override:

- existing Strong Risk bucket placement;
- hard-evidence review placement;
- wallet ranking placement;
- exported full candidate rows.

This is the policy ambiguity this RFC addresses.

## Policy Options

### Option 1: Keep Current Behavior

Description: keep existing score reducers and placement behavior unchanged.

Expected benefit:

- Lowest regression risk.
- Preserves existing analyst recall.
- Preserves existing Strong Risk and hard-evidence review semantics.
- No UI/report/report-loader change.

False negative risk:

- Lowest immediate false-negative risk because high-review placement remains broad.

False positive / confusion risk:

- Weak-history near-certain later winners can remain highly visible.
- Analysts may overread high placement despite reducer text.

Files likely affected:

- None if no implementation.

Tests required before adoption:

- No new runtime tests required.
- Continue running known-case and Event Forensic focused tests.

Product approval needed:

- No.

Expanded live validation needed:

- No, if the team accepts current ambiguity.

Rollback strategy:

- No runtime change.

### Option 2: Stronger Weak-History Reducer

Description: apply a stronger score-level penalty for rows that combine weak history, near-certain economic entry, and later win.

Expected benefit:

- Reduces Event Forensic score for the exact reproduced pattern.
- Keeps policy mostly within existing scoring/reducer model.
- Smaller user-facing change than review-bucket demotion.

False negative risk:

- Could suppress real early informed traders whose public history is weak but whose current trade has independent context.
- Could suppress new or low-history wallets in genuinely suspicious events.

False positive / confusion risk:

- Score-only changes may not resolve high placement if current-model `Strong Risk` or hard-evidence review still controls sort bucket.
- Analysts may see lower Event Forensic score but still see a high-ranked Strong Risk row.

Files likely affected:

- `app/event_forensic.py`;
- Event Forensic score tests;
- model-policy docs;
- possibly candidate audit expected fixtures.

Tests required before adoption:

- weak-history near-certainty score regression tests;
- low-probability true-positive preservation tests;
- Strong Risk/HER/funding/candidate-admission non-mutation tests;
- old report compatibility tests;
- known-case benchmark run.

Product approval needed:

- Recommended, but not strictly required if score-only and no placement semantics change.

Expanded live validation needed:

- Recommended on more than one event before changing production scoring.

Rollback strategy:

- Revert the additional score reducer and keep current reducer copy.

### Option 3: Review-Bucket Demotion

Description: keep the score if desired, but move weak-history near-certain later-win rows out of the primary/high review bucket unless explicit independent hard evidence overrides the demotion.

Expected benefit:

- Directly addresses the reproduced high-rank concern.
- Keeps rows exported and reviewable while reducing primary-list prominence.
- Aligns analyst workflow with the existing reducer language: weak-history near-certain later wins are context unless independent evidence exists.

False negative risk:

- May move true but subtle informed trades out of primary view.
- Requires careful override design for independent evidence, linked wallets, funding, and real low-probability wins.

False positive / confusion risk:

- If not clearly labeled, analysts may think demoted rows disappeared.
- Report/UI semantics change because placement changes even when score remains available.

Files likely affected:

- `app/event_forensic.py`;
- Event Forensic browser/report payload tests;
- candidate audit tests;
- saved report compatibility tests;
- possibly browser labels if new bucket text is added.

Tests required before adoption:

- primary vs secondary bucket placement contract;
- rows remain in JSON/CSV exports;
- old reports load absent-safe;
- weak-history near-certainty rows with independent proof remain reviewable;
- Strong Risk/HER/funding/candidate-admission gates are not changed directly;
- known-case benchmark;
- live/saved validation before/after comparison.

Product approval needed:

- Yes. This changes analyst-facing review placement semantics.

Expanded live validation needed:

- Recommended before implementation and required before tuning exceptions.

Rollback strategy:

- Remove placement override and preserve the exported warning fields.
- Keep additive audit fields if they were added and are absent-safe.

### Option 4: Explanation-Only / Analyst Warning

Description: keep scores and ranking unchanged, but add stronger warning/context fields for weak-history near-certain later-win rows.

Expected benefit:

- Clarifies interpretation without changing model behavior.
- Low runtime risk if fields are additive and old-report safe.
- Useful if product goal is analyst caution rather than lower prominence.

False negative risk:

- Low, because ranking stays unchanged.

False positive / confusion risk:

- Does not solve high-rank concern.
- Analysts can still overweight visible rank despite stronger warning copy.

Files likely affected:

- `app/event_forensic.py` additive payload fields only;
- Event Forensic report/UI copy tests if surfaced;
- old-report compatibility tests.

Tests required before adoption:

- additive field presence;
- old-report absent-safe rendering;
- no score/sort/gate mutation;
- known-case warning contract.

Product approval needed:

- Recommended if warning is visible in UI/report.

Expanded live validation needed:

- Not required for explanation-only, but useful for checking whether warning copy is sufficient.

Rollback strategy:

- Stop emitting the additive warning field or hide it in UI/report rendering.

## Sidecar Simulation Summary

`tools/event_forensic_weak_history_policy_simulation.py` reads existing local outputs only. It does not import or call the analyzer.

Simulation results:

| Option | affected rows | high-rank affected | demoted | warning-only | score-adjustment-only |
|---|---:|---:|---:|---:|---:|
| current | 4 | 3 | 0 | 0 | 0 |
| stronger reducer | 4 | 3 | 0 | 0 | 4 |
| review-bucket demotion | 4 | 3 | 4 | 0 | 0 |
| explanation-only | 4 | 3 | 0 | 4 | 0 |

The simulation recommends `review_bucket_demotion` only as a product-decision candidate, not implementation-ready.

## Recommended Direction

Recommended option for product decision: Option 3, Review-bucket demotion.

Reason:

- the reproduced issue is placement ambiguity, not missing reducer execution;
- score-only policy may not move rows that are high because of existing Strong Risk or hard-evidence buckets;
- explanation-only is safer but does not address high placement;
- demotion directly matches the policy statement that weak-history near-certain later wins are contextual unless independent evidence justifies primary review.

This recommendation still requires product approval and a later implementation RFC. It is not ready for direct code implementation.

## Required Implementation RFC Before Code

A future implementation RFC must define:

- exact demotion predicate;
- exact independent-evidence override predicate;
- whether demotion affects trades only, wallets, clusters, or all three;
- whether demotion changes UI primary list, JSON payload fields, CSV exports, or report markdown;
- exact absent-safe behavior for old reports;
- exact tests for Strong Risk/HER/funding/candidate-admission non-mutation;
- rollback plan.

## Stop Conditions

Stop before implementation if:

- the proposal changes scoring weights or thresholds;
- the proposal changes direct Strong Risk, HER, funding, or candidate-admission gates;
- the proposal requires Phase 3 capital-at-risk;
- the proposal changes UI sorting/filtering without product approval;
- old reports cannot load absent-safe;
- rows would disappear from JSON/CSV exports instead of being demoted or annotated;
- additional live/RPC evidence contradicts the current single-event evidence.

## Gate Decision

Decision: `policy_ready_for_product_decision`.

The next step is a product decision on whether high-rank weak-history near-certain later-win rows should remain primary-review visible, be demoted to secondary/context review, or only receive stronger explanation copy.
