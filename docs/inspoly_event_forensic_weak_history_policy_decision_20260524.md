# InsPoly Event Forensic Weak-History Policy Decision Report

- Date: 2026-05-24
- Runtime implementation: false
- Network/RPC used by this decision report: false
- Evidence JSON: `validation_outputs/event_forensic_weak_history_policy_evidence_20260524.json`
- Simulation JSON: `validation_outputs/event_forensic_weak_history_policy_simulation_20260524.json`
- RFC: `docs/inspoly_event_forensic_weak_history_model_policy_rfc_20260524.md`

## Live Validation Summary

The bounded live/RPC validation gate was `weak_history_live_validation_needs_model_rfc`.

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
| Phase 4 cluster direction mismatches | 0 |

Interpretation: the remembered pattern reproduced, but the reducers were present. This is a model-policy ambiguity, not a narrow bug.

## Policy Simulation Summary

The offline policy simulator collected 23 rows from the live output bundle and summary. Four rows matched the weak-history near-certain later-win policy pattern, including three high-rank rows.

| Option | affected rows | high-rank affected | demoted | warning-only | score-adjustment-only |
|---|---:|---:|---:|---:|---:|
| current | 4 | 3 | 0 | 0 | 0 |
| stronger reducer | 4 | 3 | 0 | 0 | 4 |
| review-bucket demotion | 4 | 3 | 4 | 0 | 0 |
| explanation-only | 4 | 3 | 0 | 4 | 0 |

Unknown/missing field rows in the broader collected set: 19. These are mostly non-target rows where weak-history/later-win fields are not sufficient for this specific policy predicate.

## Recommended Option

Recommended option: `review_bucket_demotion`.

Reason:

- The issue is placement ambiguity. Existing reducers already reduce score and explain the concern.
- A stronger score reducer alone may not solve rows that are high because of existing Strong Risk or hard-evidence review placement.
- Explanation-only is safer but does not solve high-rank placement.
- Review-bucket demotion directly expresses the intended analyst policy: weak-history near-certain later wins should be context/secondary unless independent evidence justifies primary review.

## Implementation Safety

Implementation is not currently approved and should not begin from this report alone.

Implementation can be safe only if a later RFC defines:

- exact demotion predicate;
- exact override for independent hard evidence;
- whether wallets/clusters are affected or only trade rows;
- additive report fields and old-report fallback behavior;
- direct tests proving no scoring weight/threshold change;
- direct tests proving no Strong Risk/HER/funding/candidate-admission gate change;
- direct tests proving rows remain visible in JSON/CSV exports.

## Product Approval Requirement

Product approval is required before implementation because review-bucket demotion changes analyst-facing placement semantics.

This is more than a technical fix. It decides whether the review UI should prioritize structural/current-model risk even when Event Forensic reducers say weak-history near-certainty later wins are contextual.

## Additional Live/RPC Requirement

Additional live/RPC validation is not required to make a product decision on the current evidence, but it is recommended before implementation if the demotion policy will include nuanced overrides.

At minimum, an implementation RFC should replay:

- the current Russia/Ukraine ceasefire case;
- at least one case where a weak-history row also has independent hard evidence;
- at least one low-probability true-positive control where near-certainty does not apply.

## Gate Decision

Decision: `policy_ready_for_product_decision`.

Do not mark this implementation-ready yet. Review-bucket demotion changes review placement and analyst-facing semantics, so it needs product approval first.

## What Remains Blocked

- Runtime scoring changes.
- Scoring weight or threshold changes.
- Strong Risk/HER/funding/candidate-admission gate changes.
- Phase 3 capital-at-risk normalization.
- UI sorting/filtering changes.
- Storage schema changes.
- Live/RPC/network follow-up without explicit approval.
- Commit, push, or staging without explicit approval.
