# PR Body Replacement - InsPoly Local Release Candidate V4

```markdown
## Summary

This Draft PR publishes InsPoly Local Release Candidate V4 for human review.

RC V4 is a large local-first release candidate covering:

- corrected Polymarket side/outcome semantics;
- safer Event Forensic review behavior;
- selected-market vs whole-event scope metadata;
- local browser offline assets;
- expanded benchmark and validation coverage;
- sidecar indexer / warehouse tooling;
- optional top-level `indexerWarehousePointer` metadata;
- strategic control docs for future Codex work.

## Explicit Non-Goals

This PR does not introduce:

- trading, order placement, private keys, or CLOB auth;
- Phase 3 capital runtime;
- scoring/gate/funding/HER/candidate-admission rewrites;
- production warehouse daemon, scheduler, or background worker;
- live indexer integration into scanner/archive/Event Forensic/browser runtime;
- copied warehouse metrics in reports;
- browser UI panels for warehouse data;
- report sorting/filtering changes;
- saved report mutation;
- production storage schema migration.

## Reviewer Starting Points

- Release overview: `docs/inspoly_rc_v4_github_release_overview_20260528.md`
- Architecture map: `docs/inspoly_rc_v4_architecture_map_20260528.md`
- Data-flow schemas: `docs/inspoly_rc_v4_data_flow_schemas_20260528.md`
- Reviewer guide: `docs/inspoly_rc_v4_reviewer_guide_20260528.md`
- Final reviewer addendum: `docs/inspoly_rc_v4_final_reviewer_addendum_20260528.md`
- Validation matrix: `docs/inspoly_rc_v4_validation_matrix_20260528.md`
- PR local verification: `docs/inspoly_rc_v4_pr_local_verification_20260528.md`
- Not included / still blocked: `docs/inspoly_rc_v4_not_included_still_blocked_20260528.md`
- Merge checklist: `docs/inspoly_rc_v4_merge_checklist_20260528.md`
- Rollback and local artifacts: `docs/inspoly_rc_v4_rollback_and_local_artifacts_20260528.md`

## Validation

Latest PR-readiness validation:

- Full unittest discovery: 1240 tests passed.
- Compile checks passed for `app`, `tools`, and `tests`.
- JSON validation passed for changed compact JSON.
- Runtime import scan passed.
- Copied warehouse metrics scan passed.
- Privacy/secret scan passed after committed local path redaction.
- `git diff --check` and staged diff checks passed.

GitHub currently reports no Actions workflow runs or commit statuses. This is documented as an explicit no-CI policy for this Draft PR in `docs/inspoly_rc_v4_no_ci_release_policy_20260528.md`.

## Packaging Notes

Tracked historical `release_manifests/` files were removed from this PR branch during finalization. Local manifest buckets remain local-only and are ignored.

Small synthetic Phase 3 review packet files remain included as review evidence; they do not authorize Phase 3 runtime.

## Current Gate

The PR should remain Draft until the owner explicitly chooses to mark it ready for review.

Merge is a separate explicit owner approval after review.
```
