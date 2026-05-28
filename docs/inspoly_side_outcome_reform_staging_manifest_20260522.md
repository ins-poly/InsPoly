# InsPoly Side/Outcome Reform Staging Manifest

- Date: 2026-05-22
- Scope: cleanup and staging plan only
- Runtime code changed by this manifest: false
- Tests changed by this manifest: false
- Git staging performed: false
- Commit/push performed: false
- Readiness: `ready_for_manual_staging_decision`

This manifest narrows the broad local worktree into explicit staging buckets for a future Side/Outcome reform commit. It does not delete, revert, stage, commit, or push anything.

## Recommended Commit Scope

Recommended scope for a Side/Outcome reform commit:

- Phase 1 additive raw-token/economic-side report and display clarity.
- Phase 2 approved runtime migration from raw-token model probability to economic-side model probability where side/outcome/price normalize safely.
- Phase 4 approved runtime migration of same-side/cluster grouping to normalized economic direction where safe.
- Phase 2/3/4 sidecar audits, tests, fixtures, and RFC/readiness docs that explain and reproduce the gates.
- Explicitly exclude Phase 3 runtime capital-at-risk implementation, generated review packets, shadow-context sidecar campaign outputs, indexer/protocol/ledger sidecar work, and local agent memory.

## Worktree Classification Summary

Current visible worktree before this manifest:

- Modified tracked files: `11`.
- Visible untracked files: `188`.
- Ignored local docs/RFC/audit/memory files relevant to this decision: `PROJECT_MEMORY.md`, `docs/*`, `rfcs/*`, and `side_outcome_audits/*`.

Buckets:

1. Side/Outcome runtime commit: runtime/browser files plus central helper.
2. Side/Outcome tests/fixtures: Phase 1/2/3/4 executable contracts and synthetic fixtures.
3. Side/Outcome reproducibility tools: audit and drift tools needed to reproduce gate decisions.
4. Side/Outcome docs: RFCs, impact reports, runtime/stabilization reports, release readiness, and this manifest.
5. Generated evidence needing user decision: audit JSON/Markdown outputs and sensitive-case review packets.
6. Local-only/do-not-stage: shadow packets, donor/shadow/indexer/protocol/ledger sidecar files, benchmark sidecar changes, unrelated ignored docs/RFCs, and `PROJECT_MEMORY.md`.

## Exact Files To Stage For One Side/Outcome Reform Commit

The same list is in:

- `release_manifests/side_outcome_reform_stage_recommended_20260522.txt`

Runtime and browser compatibility:

- `app/archive_scanner.py`
- `app/browser_desktop.py`
- `app/browser_event_forensic_ui.html`
- `app/browser_ui.html`
- `app/event_forensic.py`
- `app/scanner.py`
- `app/side_outcome.py`

Tests and fixtures:

- `tests/test_app_workflow_contracts.py`
- `tests/test_cross_mode_scoring_contract.py`
- `tests/test_scanner_patterns.py`
- `tests/test_side_outcome_archive_evidence_audit.py`
- `tests/test_side_outcome_normalization.py`
- `tests/test_side_outcome_phase2_impact_audit.py`
- `tests/test_side_outcome_phase2_model_contract.py`
- `tests/test_side_outcome_phase2_post_migration_drift_audit.py`
- `tests/test_side_outcome_phase3_capital_at_risk_audit.py`
- `tests/test_side_outcome_phase4_cluster_direction_audit.py`
- `tests/test_side_outcome_phase4_post_migration_drift_audit.py`
- `tests/test_side_outcome_price_normalization_audit.py`
- `tests/fixtures/side_outcome_phase2_archive/archive_flagged.csv`
- `tests/fixtures/side_outcome_phase2_archive/archive_report.json`
- `tests/fixtures/side_outcome_phase2_archive/archive_trades.csv`
- `tests/fixtures/side_outcome_phase3_capital_at_risk/archive_rows.csv`
- `tests/fixtures/side_outcome_phase3_capital_at_risk/cases.json`
- `tests/fixtures/side_outcome_phase4_cluster_direction/archive_rows.csv`
- `tests/fixtures/side_outcome_phase4_cluster_direction/cases.json`

Reproducibility tools:

- `tools/side_outcome_archive_evidence_audit.py`
- `tools/side_outcome_phase2_impact_audit.py`
- `tools/side_outcome_phase2_post_migration_drift_audit.py`
- `tools/side_outcome_phase3_capital_at_risk_audit.py`
- `tools/side_outcome_phase4_cluster_direction_audit.py`
- `tools/side_outcome_phase4_post_migration_drift_audit.py`

Docs and manifests:

- `docs/inspoly_side_outcome_phase2_archive_evidence_gap_20260522.md`
- `docs/inspoly_side_outcome_phase2_model_migration_rfc_20260522.md`
- `docs/inspoly_side_outcome_phase2_post_migration_stabilization_20260522.md`
- `docs/inspoly_side_outcome_phase2_readiness_impact_audit_20260522.md`
- `docs/inspoly_side_outcome_phase2_runtime_migration_20260522.md`
- `docs/inspoly_side_outcome_phase3_capital_at_risk_impact_audit_20260522.md`
- `docs/inspoly_side_outcome_phase3_capital_at_risk_rfc_20260522.md`
- `docs/inspoly_side_outcome_phase4_cluster_direction_impact_audit_20260522.md`
- `docs/inspoly_side_outcome_phase4_cluster_direction_rfc_20260522.md`
- `docs/inspoly_side_outcome_phase4_post_migration_stabilization_20260522.md`
- `docs/inspoly_side_outcome_phase4_runtime_migration_20260522.md`
- `docs/inspoly_side_outcome_reform_release_readiness_20260522.md`
- `docs/inspoly_side_outcome_reform_staging_manifest_20260522.md`
- `rfcs/SIDE_OUTCOME_PRICE_NORMALIZATION_RFC_20260507.json`
- `rfcs/SIDE_OUTCOME_PRICE_NORMALIZATION_RFC_20260507.md`
- `release_manifests/side_outcome_reform_do_not_stage_20260522.txt`
- `release_manifests/side_outcome_reform_stage_recommended_20260522.txt`
- `release_manifests/side_outcome_reform_user_decision_20260522.txt`

Ignored files in this recommended list require a force-add or `.gitignore` allow-list adjustment:

- all `docs/inspoly_side_outcome_*.md`;
- `rfcs/SIDE_OUTCOME_PRICE_NORMALIZATION_RFC_20260507.*`.

## Exact Files Needing User Decision

The same list is in:

- `release_manifests/side_outcome_reform_user_decision_20260522.txt`

Generated audit outputs:

- `side_outcome_audits/side_outcome_phase2_archive_evidence_gap_20260522.json`
- `side_outcome_audits/side_outcome_phase2_post_migration_drift_audit_20260522.json`
- `side_outcome_audits/side_outcome_phase2_readiness_impact_audit_20260522.json`
- `side_outcome_audits/side_outcome_phase2_runtime_migration_verification_20260522.json`
- `side_outcome_audits/side_outcome_phase3_capital_at_risk_audit_20260522.json`
- `side_outcome_audits/side_outcome_phase4_cluster_direction_audit_20260522.json`
- `side_outcome_audits/side_outcome_phase4_post_migration_drift_audit_20260522.json`
- `side_outcome_audits/side_outcome_phase4_runtime_migration_verification_20260522.json`
- `side_outcome_audits/side_outcome_price_normalization_audit_20260507.json`
- `side_outcome_audits/side_outcome_price_normalization_audit_20260507.md`

Generated review packets:

- `side_outcome_review_packets/phase2_post_migration_sensitive_cases_20260522/index.md`
- `side_outcome_review_packets/phase2_post_migration_sensitive_cases_20260522/sensitive_cases.json`
- `side_outcome_review_packets/phase2_post_migration_sensitive_cases_20260522/summary.json`
- `side_outcome_review_packets/phase4_post_migration_sensitive_merge_groups_20260522/index.md`
- `side_outcome_review_packets/phase4_post_migration_sensitive_merge_groups_20260522/sensitive_merge_groups.json`
- `side_outcome_review_packets/phase4_post_migration_sensitive_merge_groups_20260522/summary.json`

Private/local detection reference docs touched during Phase 1:

- `docs/event_forensic_score_sort_modes_20260511.md`
- `docs/inspoly_detection_logic_full_export.md`

Why user decision is required:

- These files are useful evidence, but they are generated or ignored local docs.
- Including them improves audit reproducibility.
- Excluding them keeps the public/source commit smaller and avoids committing timestamped review artifacts.

## Exact Files Not To Stage For The Side/Outcome Commit

The exhaustive path list is in:

- `release_manifests/side_outcome_reform_do_not_stage_20260522.txt`

Main categories:

- `PROJECT_MEMORY.md`: local agent memory; keep local unless the repository explicitly decides to version it.
- `shadow_review_packets/`: generated shadow-context review packets.
- `app/indexer/`, `app/polymarket_protocol.py`, `app/polymarket_ledger.py`: donor/protocol/indexer/ledger sidecar work, not part of this Side/Outcome commit.
- `app/shadow_metrics.py`, `app/microstructure_context.py`, `app/trader_profile_context.py`, `app/benchmark_cases.py`: shadow/benchmark sidecar work, not part of this Side/Outcome commit.
- `tests/test_benchmark_schema_compatibility.py` and benchmark/shadow/indexer/protocol/ledger tests/fixtures: unrelated to this commit.
- `tools/shadow_*`, `tools/batch_*`, `tools/evaluate_*`, `tools/render_shadow_*`, `tools/indexer_fixture_dry_run.py`, `tools/validate_polymarket_ledger_against_artifacts.py`: sidecar campaign tools for a separate checkpoint.
- `docs/inspoly_reform_*` and non-side-outcome ignored RFC/docs: donor/shadow campaign docs or older local docs.

## Risk Of Including Generated Evidence

- Review size increases quickly: generated JSON and packet directories add many files with timestamped names.
- Some outputs may contain local artifact paths or case-specific context that is useful locally but noisy in a source commit.
- Future generated reruns will create churn unless `.gitignore` keeps timestamped evidence out of normal status.

## Risk Of Excluding Generated Evidence

- Reviewers can inspect source/tests/docs but cannot reproduce exact local affected-count snapshots without rerunning tools.
- The rationale for sensitive case decisions becomes less self-contained.
- If docs reference JSON outputs that are not committed, links become local-only evidence references.

Balanced recommendation:

- Commit source, tests, fixtures, tools, RFC/report markdown.
- Do not commit review packets by default.
- Commit selected final audit JSON only if the maintainer wants machine-readable evidence in the repository.

## Commit Split Recommendation

### Option 1: One consolidated commit

Scope:

- Runtime/browser Side/Outcome files.
- Side/Outcome tests/fixtures.
- Side/Outcome audit tools.
- Side/Outcome docs/manifests.
- Optional selected audit JSON if approved.

Pros:

- One checkpoint captures the complete causal chain from RFC to runtime to stabilization.
- Easier rollback to the previous public state.
- Full suite already passed on the combined worktree.

Cons:

- Large review surface.
- Sidecar audit files and runtime files are mixed.
- Generated-evidence decision can delay the whole commit.

### Option 2: Split commits

Suggested split:

1. Runtime + executable tests:
   - `app/side_outcome.py`
   - scanner/archive/Event Forensic/browser runtime changes
   - Side/Outcome tests and fixtures
2. RFCs/docs:
   - Side/Outcome RFCs, impact reports, stabilization reports, release readiness, staging manifest
3. Audit tools/fixtures:
   - Phase 2/3/4 audit tools and any fixtures not already included in runtime tests
4. Generated evidence:
   - only if user approves selected audit JSON/review packets

Pros:

- Smaller review units.
- Generated evidence can be omitted or force-added separately.
- Easier to identify runtime behavior changes in code review.

Cons:

- Requires careful ordering because some docs reference audit tools and outputs.
- More commits to manage.
- If split poorly, tests may depend on files introduced in a later commit.

Recommended split if the maintainer wants clean review:

- Commit 1: runtime + tests + fixtures.
- Commit 2: audit tools + RFC/docs/manifests.
- Commit 3: selected generated evidence only if explicitly approved.

## Rollback Strategy

- Revert the runtime/test commit to remove Phase 1/2/4 behavior changes while leaving docs/audit files available for analysis.
- If only generated evidence is problematic, drop the generated-evidence commit without touching runtime.
- Do not mutate saved reports during rollback.
- Keep Phase 3 capital-at-risk blocked unless a separate approval gate is opened.

## Verification

Only light checks are required for this manifest step because runtime and tests were not changed.

- Run `git diff --check`.
- Record a git status summary.

No `py_compile` or full test suite is needed for this manifest-only step.
