# Event Forensic Weak-History Review-Bucket Demotion Implementation

- Date: 2026-05-24
- Approved policy option: `review_bucket_demotion`
- RFC: `docs/inspoly_event_forensic_weak_history_model_policy_rfc_20260524.md`
- Decision report: `docs/inspoly_event_forensic_weak_history_policy_decision_20260524.md`
- Verification output: `validation_outputs/event_forensic_weak_history_review_bucket_demotion_verification_20260524.json`

## Scope

This implementation changes Event Forensic review placement only. It does not change `_event_forensic_score()`, scoring weights, thresholds, Strong Risk/HER/funding/candidate-admission gates, storage schema, live/RPC behavior, or Phase 3 capital-at-risk logic.

Rows are not hidden and are not removed from export coverage. The primary `display_trades` / `suspicious_trades` list excludes demoted rows, while the demoted rows remain available through the report JSON `review_required_trades` / `display_review_required_trades` fields and through the candidate audit JSON/CSV/Markdown exports.

## Behavior Changed

Event Forensic now applies a central review-placement predicate to visible candidate trade payloads before building the primary review list.

A row is moved from primary/high review placement to the `weak_history_near_certainty_review_required` secondary review bucket only when all required evidence is available and all of these conditions hold:

- it would otherwise be primary/high placement through current/retrospective Strong Risk, hard-evidence review, or Event Forensic primary threshold routing;
- `laterWon` is true;
- economic-side probability is available from normalized Side/Outcome model context;
- economic-side probability is at or above the existing `NEAR_CERTAINTY_PRICE` threshold;
- weak-history evidence is present through Event Forensic flags/reducers/summary/raw metrics.

The predicate returns conservative non-demotion when later correctness is unknown/false, economic probability is missing or malformed, side/outcome normalization is not safe, weak-history evidence is absent/unknown, the row is already secondary context, or the row is a lower-probability informed call.

## Additive Fields

New reports may include these additive fields on trade payloads and candidate audit rows:

- `weakHistoryNearCertaintyReviewDemotion`
- `weakHistoryNearCertaintyReviewReason`
- `reviewBucketBeforePolicy`
- `reviewBucketAfterPolicy`

Old reports do not need these fields. Missing fields are treated as absent-safe and do not trigger demotion.

## Affected Simulated Rows

The post-implementation verification replayed the bounded live/RPC validation output offline:

| Metric | Count |
|---|---:|
| rows evaluated from live display | 23 |
| runtime predicate matches | 4 |
| high-rank predicate matches | 3 |
| rows hidden or removed from exports | 0 |

The three reproduced high-rank weak-history near-certain later-win rows are now classified for secondary review-required placement in the verification output.

## Visibility And Export Guarantees

- `eventForensicScore` is preserved.
- `Hard Evidence Review` source fields are preserved.
- `Strong Risk` gate attribution fields are preserved.
- Candidate audit exports include the demoted rows and the additive policy fields.
- Primary suspicious-trade CSV remains a primary-review export; demoted rows remain in candidate audit exports.
- Saved historical reports remain loadable because report loaders do not require the new fields.

## Remaining Risks

- Analyst-facing placement changed by design; analysts should use candidate audit or `review_required_trades` for the demoted context rows.
- This policy does not tune the score model. If future evidence suggests the score itself is wrong, that requires a separate model RFC.
- This policy does not solve Phase 3 capital-at-risk semantics.
- This policy does not broaden live/RPC validation coverage beyond the bounded reproduced case.

## Rollback

Rollback is local and narrow:

1. Remove the weak-history near-certainty review-policy annotation and filtering from Event Forensic review-list assembly.
2. Remove the additive policy fields from Event Forensic CSV/candidate audit exports.
3. Keep the RFC, decision report, and verification evidence as historical context.

No storage migration or saved-report mutation is required.

## Verification

Focused verification performed for the implementation:

- `python3 -m py_compile app/event_forensic.py tests/test_event_forensic_weak_history_review_demotion.py`
- `python3 -m unittest tests.test_event_forensic_weak_history_review_demotion`

Additional suite verification is recorded in `PROJECT_MEMORY.md` after the implementation run.
