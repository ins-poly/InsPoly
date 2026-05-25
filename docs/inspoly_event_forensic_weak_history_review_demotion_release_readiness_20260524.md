# Event Forensic Weak-History Review Demotion Release Readiness

- Date: 2026-05-24
- Gate: `review_demotion_ready_for_commit_review`
- Post-validation output: `validation_outputs/event_forensic_weak_history_review_demotion_post_validation_20260524.json`
- Implementation report: `docs/inspoly_event_forensic_weak_history_review_bucket_demotion_implementation_20260524.md`
- Runtime scope: Event Forensic review placement/routing only
- Live/RPC used for this readiness pass: false

## What Changed

Event Forensic now applies the approved `review_bucket_demotion` policy after trade payload construction and before primary review-list assembly.

Rows matching the full weak-history near-certainty later-win predicate are moved out of primary/high Event Forensic placement and into `weak_history_near_certainty_review_required`.

The central predicate is `_weak_history_near_certainty_review_demotion()` and it is applied through `_annotate_weak_history_near_certainty_review_policy()`. The predicate is conservative: missing or malformed side/outcome/probability, unknown `laterWon`, absent weak-history evidence, non-near-certain economic probability, or already-secondary rows do not demote.

## What Did Not Change

- `_event_forensic_score()` score math was not tuned for this policy.
- Scoring weights did not change.
- Thresholds did not change.
- Strong Risk, HER, funding, and candidate-admission gates were not directly changed.
- Phase 3 capital-at-risk normalization was not implemented.
- Storage schema did not change.
- Live/RPC/network behavior did not change.
- UI sorting/filtering was not redesigned.
- Saved reports/artifacts were not mutated.
- Rows are not hidden or removed from exports.

## Additive Fields

New reports may include these fields:

- `weakHistoryNearCertaintyReviewDemotion`
- `weakHistoryNearCertaintyReviewReason`
- `reviewBucketBeforePolicy`
- `reviewBucketAfterPolicy`
- `review_required_trades`
- `display_review_required_trades`

Old reports without these fields remain absent-safe. Missing fields do not trigger demotion.

## Post-Validation Counts

| Metric | Count |
|---|---:|
| policy simulation rows evaluated | 23 |
| live display rows evaluated | 19 |
| rows demoted in live replay | 4 |
| high-rank rows demoted | 3 |
| rows remaining primary in live replay | 15 |
| policy-simulation rows with insufficient fields | 19 |
| live rows with insufficient policy evidence | 15 |
| known-case benchmark cases | 16 |
| known-case benchmark failures | 0 |
| false-positive guard cases covered | 6 |
| old-report fallback cases covered | 1 |
| rows hidden or removed from exports | 0 |

## Compatibility

Compatibility is preserved through additive-only report fields and conservative fallback:

- Primary `suspicious_trades` remains a primary-review list.
- `review_required_trades` keeps demoted rows available in report JSON.
- Candidate audit JSON/CSV/Markdown keeps demoted rows and includes before/after bucket metadata.
- Old report rows without demotion fields remain loadable and do not synthesize demotion.
- Known-case benchmark still covers malformed fallback and old-report fallback.

## Rollback

Rollback is narrow:

1. Remove `_annotate_weak_history_near_certainty_review_policy()` from Event Forensic review-list assembly.
2. Remove the weak-history near-certainty predicate and additive report fields.
3. Keep the policy RFC, implementation report, and validation outputs as historical evidence.

No storage migration or saved-report rewrite is required.

## Verification

Executed during this readiness pass:

- `python3 -m py_compile app/event_forensic.py tests/test_event_forensic_weak_history_review_demotion.py`
- `python3 -m unittest tests.test_event_forensic_weak_history_review_demotion tests.test_event_forensic_weak_history_policy_simulation tests.test_known_case_benchmark tests.test_side_outcome_phase2_model_contract tests.test_side_outcome_phase4_cluster_direction_audit tests.test_cross_mode_scoring_contract tests.test_scanner_patterns`
- `python3 -m unittest discover -s tests -p 'test_*.py'`
- `git diff --check`
- direct scans for forbidden scope bleed

Results:

- Focused suite: 244 tests OK.
- Full suite: 936 tests OK.
- Existing sqlite `ResourceWarning` noise and the known validation terminal artifact message still appear, but no failures occurred.

## Remaining Blocked Items

- scorer tuning;
- scoring weight or threshold changes;
- direct Strong Risk/HER/funding/candidate-admission changes;
- Phase 3 capital-at-risk normalization;
- storage schema changes;
- live/RPC/network validation without explicit approval;
- UI sorting/filtering changes without explicit approval;
- commit/push/staging without explicit approval.

## Release Gate

Decision: `review_demotion_ready_for_commit_review`.

The implementation is ready for manual commit review from a validation standpoint. The broad worktree still contains many previous uncommitted sidecar/docs/test/generated artifacts, so staging policy remains a separate user decision.
