# InsPoly Codex Commit Packaging Campaign Instruction

- Date: 2026-05-25
- Intended use: paste the short prompt below into a new Codex thread and tell it to execute this file.
- Scope: classify the broad local worktree, produce exact staging manifests, and propose split commits.
- Default behavior: no staging, no commit, no push.
- Expected duration: long run. Do not stop after a shallow `git status` summary.

## Short Prompt For The Next Thread

Use this exact prompt in the next Codex thread:

```text
Read and execute this file fully:
/Users/Root1/Documents/InsPoly/docs/inspoly_codex_commit_packaging_campaign_instruction_20260525.md

Work autonomously through the full packaging campaign. Do not stage, commit, push, delete, or revert anything. Produce exact split-commit manifests and a final packaging recommendation.
```

## Purpose

The InsPoly worktree now contains several completed but uncommitted campaigns:

- Side/Outcome Phase 1/2/4 runtime reform and tests.
- Side/Outcome Phase 3 audit/RFC, with runtime still blocked.
- Event Forensic weak-history live/RPC validation.
- Event Forensic weak-history model-policy RFC.
- Approved Event Forensic review-bucket demotion implementation and post-validation.
- Benchmark Suite V2 and known-case benchmark tooling.
- Strategic long-run reports and validation outputs.
- Earlier shadow/indexer/protocol/ledger sidecar campaigns.
- Generated JSON outputs and review packets.
- Local `PROJECT_MEMORY.md` entries.

The next task is not more model work. The next task is packaging.

The campaign must answer:

1. Which files should be staged for commit review?
2. Which files should be split into separate commits?
3. Which files should remain local-only?
4. Which files require explicit user decision because they are generated, ignored, large, timestamped, private, or evidence-only?
5. Which files are unrelated/pre-existing and must not be mixed into the current release?

The output must be exact enough that a later approved thread can run `git add` from manifest files without guessing.

## Current Technical State To Preserve

As of this instruction:

- Side/Outcome Phase 2 is stable.
- Side/Outcome Phase 4 is stable.
- Side/Outcome Phase 3 remains blocked: `keep_phase3_blocked`.
- Event Forensic weak-history review-bucket demotion is implemented.
- Event Forensic weak-history review demotion release gate: `review_demotion_ready_for_commit_review`.
- Full suite after the latest runtime change: 936 tests OK.
- No commit, push, or staging has been performed.

Current remaining blockers:

- Phase 3 capital-at-risk runtime normalization.
- Scoring weight/threshold changes.
- Direct Strong Risk/HER/funding/candidate-admission migrations.
- Event-level selected-market versus whole-event runtime semantics, pending product decision.
- UI sorting/filtering changes.
- Storage schema changes.
- Live/RPC/network/indexing/trading changes.

These blockers must not be unblocked by a packaging task.

## Non-Negotiable Rules

The next Codex must obey all repository instructions in:

- `/Users/Root1/Documents/InsPoly/AGENTS.md`
- `/Users/Root1/Documents/InsPoly/PROJECT_MEMORY.md`

Hard prohibitions:

- Do not stage files.
- Do not commit.
- Do not push.
- Do not delete files.
- Do not revert files.
- Do not run destructive git commands.
- Do not change runtime code.
- Do not change tests unless a manifest/test path error prevents packaging documentation from being correct.
- Do not use live/RPC/network calls.
- Do not change scoring weights or thresholds.
- Do not implement Phase 3.
- Do not change Strong Risk/HER/funding/candidate-admission gates.
- Do not change storage schema.
- Do not change UI sorting/filtering.
- Do not mutate saved reports or generated validation outputs.
- Do not decide to version generated evidence without putting it in a user-decision bucket.

Allowed:

- Read files.
- Run local git inspection commands.
- Run local tests only if needed to confirm readiness.
- Create packaging docs and manifest files.
- Update `PROJECT_MEMORY.md`.
- Create machine-readable manifest JSON.
- Run `git diff --check`.
- Run lightweight verification that does not mutate state.

## Required Startup Protocol

Before producing any manifest, read:

1. `/Users/Root1/Documents/InsPoly/AGENTS.md`
2. `/Users/Root1/Documents/InsPoly/PROJECT_MEMORY.md`
3. `/Users/Root1/Documents/InsPoly/docs/inspoly_side_outcome_reform_staging_manifest_20260522.md`
4. `/Users/Root1/Documents/InsPoly/docs/inspoly_side_outcome_reform_release_readiness_20260522.md`
5. `/Users/Root1/Documents/InsPoly/docs/inspoly_event_forensic_weak_history_review_demotion_release_readiness_20260524.md`
6. `/Users/Root1/Documents/InsPoly/docs/inspoly_event_forensic_weak_history_review_bucket_demotion_implementation_20260524.md`
7. `/Users/Root1/Documents/InsPoly/docs/inspoly_strategic_long_run_campaign_summary_20260522.md`
8. `/Users/Root1/Documents/InsPoly/docs/inspoly_known_case_benchmark_corpus_20260522.md`
9. `/Users/Root1/Documents/InsPoly/docs/inspoly_benchmark_suite_v2_productization_20260522.md`
10. Existing release manifest files under `/Users/Root1/Documents/InsPoly/release_manifests/`

Then inspect fresh local state:

- `git status --short`
- `git status --short --ignored`
- `git diff --name-only`
- `git diff --stat`
- `git ls-files --others --exclude-standard`
- `git ls-files --ignored --others --exclude-standard`

Do not rely only on old manifests. They were created before Event Forensic policy implementation and the later strategic campaign.

## Required Pre-Manifest Statement

Before writing new packaging files, state briefly:

- current visible worktree shape;
- what already exists from prior staging manifests;
- what changed since the Side/Outcome staging manifest;
- what must be preserved;
- where packaging risk is concentrated.

Packaging risk is expected to be concentrated in:

- broad untracked files;
- ignored docs and generated outputs;
- mixing runtime changes with sidecar research artifacts;
- committing local `PROJECT_MEMORY.md`;
- accidentally including shadow/indexer/protocol/ledger sidecar work in the same commit as runtime changes;
- omitting docs/tests that justify the runtime changes.

## Campaign Outputs

Create these files:

- `docs/inspoly_commit_packaging_strategy_20260525.md`
- `release_manifests/commit_packaging_summary_20260525.json`
- `release_manifests/commit_01_runtime_core_recommended_20260525.txt`
- `release_manifests/commit_02_event_forensic_policy_recommended_20260525.txt`
- `release_manifests/commit_03_benchmark_validation_tooling_recommended_20260525.txt`
- `release_manifests/commit_04_docs_rfc_reports_recommended_20260525.txt`
- `release_manifests/commit_05_optional_generated_evidence_user_decision_20260525.txt`
- `release_manifests/do_not_stage_local_only_20260525.txt`
- `release_manifests/unrelated_or_defer_to_separate_checkpoint_20260525.txt`
- `release_manifests/force_add_required_ignored_files_20260525.txt`
- `release_manifests/packaging_verification_commands_20260525.md`

If a file already exists and is clearly superseded, update it. If not, create it.

Do not use these manifests to stage anything in this campaign.

## Classification Rules

Every changed, untracked, and relevant ignored file must appear in exactly one primary classification:

1. Commit 01: runtime core recommended.
2. Commit 02: Event Forensic policy recommended.
3. Commit 03: benchmark/validation tooling recommended.
4. Commit 04: docs/RFC/reports recommended.
5. Commit 05: optional generated evidence, user decision.
6. Local-only / do not stage.
7. Unrelated or defer to separate checkpoint.

If a file could fit multiple categories, choose the category that best matches review intent and explain exceptions in the strategy document.

No path should silently disappear from classification.

## Commit 01: Runtime Core Recommended

Purpose:

Package the core production runtime and executable tests needed for the Side/Outcome model semantics and browser/report compatibility.

Likely included files:

- `app/side_outcome.py`
- `app/scanner.py`
- `app/archive_scanner.py`
- `app/browser_desktop.py`
- `app/browser_ui.html`
- `app/browser_event_forensic_ui.html`
- Side/Outcome focused runtime tests
- Side/Outcome fixtures required by those tests
- cross-mode/app workflow tests changed specifically for Side/Outcome compatibility

Candidate tests include, but are not limited to:

- `tests/test_side_outcome_normalization.py`
- `tests/test_side_outcome_price_normalization_audit.py`
- `tests/test_side_outcome_phase2_model_contract.py`
- `tests/test_side_outcome_phase4_cluster_direction_audit.py`
- `tests/test_cross_mode_scoring_contract.py`
- `tests/test_app_workflow_contracts.py`
- relevant `tests/test_scanner_patterns.py` changes

Rules:

- Include only files needed for runtime model behavior and direct compatibility tests.
- Do not include Event Forensic weak-history demotion in this commit unless the diff is too entangled to review separately.
- If `app/event_forensic.py` contains both Side/Outcome and review-demotion changes, the packaging report must call that out and recommend whether to split by commit or keep as one runtime commit.
- Do not include generated JSON evidence.

Suggested commit title:

- `Normalize side/outcome model semantics across scanner workflows`

## Commit 02: Event Forensic Policy Recommended

Purpose:

Package the approved Event Forensic weak-history near-certainty review-bucket demotion and its focused tests.

Likely included files:

- `app/event_forensic.py`
- `tests/test_event_forensic_weak_history_review_demotion.py`
- any minimal fixtures needed by that test
- any focused tests updated only because demoted rows now route to review-required bucket

Rules:

- This commit should be reviewable as a policy/routing change, not a scorer tuning change.
- It must not include score weight/threshold changes.
- It must not include Phase 3.
- It must not include live/RPC tools unless those tools are purely supporting validation and better placed in Commit 03.

Suggested commit title:

- `Demote weak-history near-certainty Event Forensic review rows`

If `app/event_forensic.py` cannot be cleanly split between Commit 01 and Commit 02, document one of these options:

- one combined runtime commit containing Side/Outcome plus demotion;
- manual patch split by hunks in a future approved staging thread;
- leave split decision for user because hunk-level staging is risky.

Do not perform hunk-level staging in this campaign.

## Commit 03: Benchmark And Validation Tooling Recommended

Purpose:

Package reproducibility tooling, benchmark registry, local validation runners, and tests that are useful but not production runtime.

Likely included files:

- `tools/run_known_case_benchmark.py`
- `tools/curate_known_case_benchmark.py`
- `tools/run_inspoly_benchmark_suite.py`
- `tools/post_side_outcome_benchmark_replay.py`
- `tools/post_side_outcome_strategic_reliability.py`
- `tools/strategic_long_run_campaign_summary.py`
- `tools/event_forensic_weak_history_saved_report_audit.py`
- `tools/event_forensic_weak_history_live_rpc_validation.py`
- `tools/event_forensic_weak_history_policy_simulation.py`
- `tools/event_level_semantics_evidence_audit.py`
- `tools/archive_visibility_monitoring_v2.py`
- `tools/browser_side_outcome_label_snapshot.py`
- Side/Outcome audit tools:
  - `tools/side_outcome_archive_evidence_audit.py`
  - `tools/side_outcome_phase2_impact_audit.py`
  - `tools/side_outcome_phase2_post_migration_drift_audit.py`
  - `tools/side_outcome_phase3_capital_at_risk_audit.py`
  - `tools/side_outcome_phase4_cluster_direction_audit.py`
  - `tools/side_outcome_phase4_post_migration_drift_audit.py`
- tests for these tools
- stable fixtures and benchmark registry files

Rules:

- Include stable source-like tools/tests/fixtures.
- Do not include bulky generated outputs by default.
- Do not include shadow/indexer/protocol/ledger sidecar tools unless the strategy explicitly creates a separate checkpoint for them.
- If live/RPC validation tool is included, ensure it is bounded and does not contain secrets or default unbounded behavior.

Suggested commit title:

- `Add local benchmark and validation tooling for forensic workflows`

## Commit 04: Docs, RFCs, And Reports Recommended

Purpose:

Package human-readable decision trail for the completed work.

Likely included docs:

- Side/Outcome RFCs and reports.
- Event Forensic live/RPC validation report.
- Event Forensic model-policy RFC.
- Event Forensic policy decision report.
- Event Forensic demotion implementation report.
- Event Forensic demotion release readiness report.
- Benchmark Suite V2 report.
- Strategic long-run campaign summaries.
- Archive visibility monitoring report.
- Browser label compatibility snapshot.
- Phase 3 unblock requirements.
- Commit packaging strategy docs and release manifests.

Rules:

- Docs under `docs/` may be ignored by `.gitignore`; list such files in `force_add_required_ignored_files_20260525.txt`.
- Do not include docs that are explicitly local/private or unrelated unless classified as user-decision.
- If docs reference generated JSON that is not committed, mark those links as local evidence in the packaging strategy.

Suggested commit title:

- `Document forensic reform gates and validation evidence`

## Commit 05: Optional Generated Evidence User Decision

Purpose:

List generated machine outputs and review packets that may or may not belong in version control.

Likely candidates:

- `side_outcome_audits/*.json`
- `side_outcome_review_packets/*`
- `validation_outputs/*.json`
- `validation_outputs/event_forensic_weak_history_live_rpc_*/`
- generated review packets
- generated strategic summaries

Rules:

- Do not recommend committing all generated evidence by default.
- For each group, state:
  - why it is useful;
  - why it is noisy;
  - whether it contains local paths;
  - whether it is reproducible;
  - whether it is timestamped churn;
  - whether reviewers need it to understand the commit.

Recommended default:

- Keep review packets local-only.
- Commit stable fixtures and source-like registry files.
- Do not commit timestamped generated JSON unless the user explicitly wants a reproducibility bundle.
- If committing generated evidence, do it in a separate commit.

Suggested optional commit title:

- `Add generated forensic validation evidence`

## Local-Only / Do Not Stage

Files likely local-only:

- `PROJECT_MEMORY.md`, unless the project explicitly versions memory.
- `shadow_review_packets/*`
- local generated packets with sensitive or noisy context.
- temporary outputs.
- large timestamped generated outputs not required by tests.

The manifest must explain that `PROJECT_MEMORY.md` has been intentionally updated throughout local agent work but may not be appropriate for source control.

If the repository actually tracks `PROJECT_MEMORY.md`, detect that with `git ls-files PROJECT_MEMORY.md` and adjust the recommendation.

## Unrelated Or Defer To Separate Checkpoint

Earlier sidecar work likely unrelated to the current runtime release:

- `app/indexer/`
- `app/polymarket_protocol.py`
- `app/polymarket_ledger.py`
- `app/shadow_metrics.py`
- `app/microstructure_context.py`
- `app/trader_profile_context.py`
- indexer tests/tools
- protocol/ledger tests/tools
- shadow metrics tests/tools
- microstructure/trader profile tests/tools
- reconstruction shadow PnL tools/tests
- shadow sidecar review packet tooling

These may be valuable, but they should not be mixed into the current runtime/Event Forensic packaging unless the strategy recommends a separate checkpoint.

Create a clear deferred-checkpoint recommendation:

- `donor_protocol_ledger_sidecar_checkpoint`
- `shadow_context_sidecar_checkpoint`
- `indexer_sidecar_checkpoint`
- `benchmark_schema_checkpoint`

Each recommendation should say why it is separate and what would need to be verified before commit.

## Force-Add / Ignore Policy Review

Because docs and generated outputs may be ignored, create:

- `release_manifests/force_add_required_ignored_files_20260525.txt`

For every ignored file that is recommended for a commit, list:

- path;
- target commit number;
- reason it is ignored;
- whether to force-add or change `.gitignore`;
- risk.

Default recommendation:

- force-add selected docs/RFCs if the repo intentionally ignores `docs/*`;
- do not change `.gitignore` in this campaign;
- do not force-add generated evidence without user approval.

## Strategy Document Requirements

Create:

- `docs/inspoly_commit_packaging_strategy_20260525.md`

It must contain:

1. Worktree summary.
2. Current release readiness state.
3. Prior manifests considered.
4. File classification summary counts.
5. Proposed split commits.
6. Exact manifest file links.
7. Generated evidence recommendation.
8. Local-only/defer recommendation.
9. Force-add/ignore policy notes.
10. Risks by commit.
11. Suggested commit titles and bodies.
12. Suggested PR structure.
13. Rollback strategy.
14. Verification commands for a future staging/commit thread.
15. Final readiness decision:
    - `ready_for_user_staging_decision`
    - `needs_manifest_fix`
    - `needs_cleanup_before_staging`

## Machine-Readable Summary Requirements

Create:

- `release_manifests/commit_packaging_summary_20260525.json`

Suggested schema:

```json
{
  "date": "2026-05-25",
  "readiness": "ready_for_user_staging_decision",
  "staging_performed": false,
  "commit_performed": false,
  "push_performed": false,
  "counts": {
    "modified_tracked": 0,
    "visible_untracked": 0,
    "ignored_candidates": 0,
    "commit_01_paths": 0,
    "commit_02_paths": 0,
    "commit_03_paths": 0,
    "commit_04_paths": 0,
    "commit_05_user_decision_paths": 0,
    "local_only_paths": 0,
    "deferred_paths": 0,
    "force_add_required_paths": 0
  },
  "commits": [
    {
      "id": "commit_01",
      "title": "Normalize side/outcome model semantics across scanner workflows",
      "manifest": "release_manifests/commit_01_runtime_core_recommended_20260525.txt",
      "risk": "medium"
    }
  ],
  "blockers": [],
  "notes": []
}
```

The exact schema can be extended, but it must remain valid JSON.

## Verification Commands Document

Create:

- `release_manifests/packaging_verification_commands_20260525.md`

Include command groups for a future staging thread:

1. Verify no forbidden files staged.
2. Verify Commit 01 after staging.
3. Verify Commit 02 after staging.
4. Verify Commit 03 after staging.
5. Verify Commit 04 after staging.
6. Optional generated evidence checks.
7. Full suite command.
8. `git diff --cached --check`.
9. Direct scans for forbidden scope bleed.

Do not run staging commands in this campaign.

## Suggested Future Commit Bodies

The strategy document should propose commit bodies, not execute them.

Commit 01 body should mention:

- economic-side model probability for BUY/SELL YES/NO;
- normalized cluster direction;
- raw/display fields preserved;
- Phase 3 blocked;
- tests.

Commit 02 body should mention:

- weak-history near-certainty review demotion;
- rows remain visible/exported;
- score weights/thresholds unchanged;
- product-policy basis;
- tests.

Commit 03 body should mention:

- local benchmark/validation suite;
- known-case corpus;
- Event Forensic saved/live validation support;
- sidecar-only tooling;
- no production imports.

Commit 04 body should mention:

- RFCs and evidence reports;
- decision trail;
- remaining blockers.

## Rollback Strategy

Document rollback by commit:

- Commit 01 rollback restores pre-Side/Outcome runtime semantics.
- Commit 02 rollback restores previous Event Forensic primary placement.
- Commit 03 rollback removes sidecar tooling/tests/fixtures but should not affect runtime.
- Commit 04 rollback removes documentation only.
- Commit 05 rollback removes generated evidence only.

Mention that if `app/event_forensic.py` is shared between Commit 01 and Commit 02, rollback may need hunk-level care unless combined.

## Verification During This Packaging Campaign

Required after writing manifests:

- `git diff --check`
- Validate JSON summary is parseable.
- Confirm every manifest file exists.
- Confirm no staging occurred:
  - inspect `git diff --cached --name-only`
- Confirm the packaging campaign did not change runtime files.

No full unittest is required because packaging docs/manifests do not alter runtime or tests. If the next Codex changes any Python helper for manifest generation, it must run `py_compile` and relevant tests.

## Memory Update

Update:

- `PROJECT_MEMORY.md`

Add:

- date;
- task;
- files changed;
- packaging readiness decision;
- manifest files created;
- staging/commit/push remained false;
- recommended split;
- user decisions required;
- verification.

## Final Response Requirements

The next Codex final response must include:

- packaging readiness decision;
- path to strategy document;
- manifest files created;
- proposed commit split;
- number of files in each split;
- files needing user decision;
- local-only/deferred categories;
- whether staging/commit/push happened;
- verification results;
- exact next prompt the user can give to stage Commit 01 later.

Keep the response focused. The manifests carry the full detail.

## Stop Conditions

Stop and report `needs_manifest_fix` if:

- a changed file cannot be classified;
- old manifests contradict current worktree in a way that cannot be resolved safely;
- generated evidence appears to contain secrets or private keys;
- the strategy would require deleting or reverting files;
- the strategy would require staging in this campaign;
- the repository state is too dirty to distinguish current work from unrelated work.

If stopped, do not stage. Produce the best partial inventory and explain what user decision is needed.
