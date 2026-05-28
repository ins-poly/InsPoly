# InsPoly Commit Packaging Strategy - 2026-05-25

This is a packaging-only checkpoint. It does not authorize staging, committing, pushing, deleting, reverting, runtime changes, scorer tuning, Phase 3 capital-at-risk implementation, gate changes, storage changes, live/RPC work, or UI sorting/filtering changes.

## Current Worktree Shape

- Modified tracked files: 11.
- Visible untracked files: 222.
- Relevant ignored packaging candidates are mostly docs, RFCs, validation outputs, and generated audit evidence.
- Full ignored runtime caches and saved app data are intentionally not enumerated as commit candidates.
- Prior Side/Outcome manifests from 2026-05-22 still exist and are superseded by this split-commit plan.

The packaging risk is concentrated in four places:

1. `app/event_forensic.py` contains both Side/Outcome Event Forensic semantics and the approved weak-history review-bucket demotion. A strict split requires manual hunk staging; otherwise combine commit 01 and commit 02.
2. Ignored docs and generated evidence need force-add only if the reviewer decides to include them.
3. Earlier donor/sidecar campaign files are still visible in the worktree and should not be pulled into the Side/Outcome/Event Forensic runtime release by accident.
4. `PROJECT_MEMORY.md` was updated throughout the campaign but should remain local working memory unless the project owner explicitly wants it committed.

## Recommended Split

### Commit 01: Runtime Core Side/Outcome

Scope: Side/Outcome Phase 1/2/4 runtime and compatibility work for scanner/archive/browser-visible payloads, excluding the entangled Event Forensic file unless hunk-split is approved.

Manifest: `release_manifests/commit_01_runtime_core_recommended_20260525.txt`

Recommended title:

```text
Normalize side/outcome model semantics
```

Recommended body:

```text
- Add shared side/outcome normalization and additive raw-token/economic-side fields.
- Migrate scanner/archive model probability and cluster direction semantics within approved Phase 2/4 scope.
- Preserve raw display fields, old report compatibility, weights, thresholds, gates, storage schema, and live/RPC behavior.
```

Review caution: Event Forensic side/outcome semantics are in `app/event_forensic.py`, which is classified in commit 02 because the later weak-history policy change is in the same file. Use hunk staging only if the reviewer can keep both intermediate commits testable.

### Commit 02: Event Forensic Weak-History Policy

Scope: Approved `review_bucket_demotion` implementation and focused Event Forensic demotion tests.

Manifest: `release_manifests/commit_02_event_forensic_policy_recommended_20260525.txt`

Recommended title:

```text
Demote weak-history near-certain Event Forensic review rows
```

Recommended body:

```text
- Add conservative Event Forensic review-bucket demotion for weak-history near-certain later-winning rows.
- Preserve scores, weights, thresholds, exports, row visibility, direct Strong Risk/HER/funding/candidate gates, storage schema, and live/RPC behavior.
- Add additive policy explanation fields and focused regression coverage.
```

Review caution: If commit 01 and 02 cannot be safely separated because of `app/event_forensic.py`, prefer a single combined runtime/policy commit over fragile hunk staging.

### Commit 03: Benchmark And Validation Tooling

Scope: Offline reproducibility tools, curated benchmark corpus, strategic validation tools, side/outcome audit tools, and their focused tests/fixtures.

Manifest: `release_manifests/commit_03_benchmark_validation_tooling_recommended_20260525.txt`

Recommended title:

```text
Add offline reform validation tooling
```

Recommended body:

```text
- Add known-case benchmark corpus and offline benchmark replay tooling.
- Add Side/Outcome Phase 2/3/4 audit tools and focused fixtures.
- Add Event Forensic weak-history validation/simulation tooling and saved-report reliability checks.
- Keep all tools offline/read-only by default; no production imports, live/RPC calls, or storage mutation are introduced by these tools.
```

### Commit 04: Docs, RFCs, Reports, And Packaging Manifests

Scope: RFCs, readiness reports, stabilization reports, strategic reports, and this packaging strategy.

Manifest: `release_manifests/commit_04_docs_rfc_reports_recommended_20260525.txt`

Recommended title:

```text
Document side/outcome and Event Forensic reform readiness
```

Recommended body:

```text
- Add Side/Outcome RFCs, audit reports, runtime/stabilization notes, and release readiness docs.
- Add Event Forensic weak-history live validation, policy RFC, product decision, implementation, and release readiness docs.
- Add benchmark/strategic follow-up docs and exact split-commit manifests.
```

Many docs are ignored by local git rules. See `release_manifests/force_add_required_ignored_files_20260525.txt` before staging.

### Commit 05: Optional Generated Evidence

Scope: JSON audit outputs, review packets, and bounded live/RPC validation output.

Manifest: `release_manifests/commit_05_optional_generated_evidence_user_decision_20260525.txt`

Default recommendation: do not include commit 05 in the normal runtime PR. Keep generated evidence local unless the reviewer wants full audit reproducibility in git.

Pros of including commit 05:

- Better reproducibility for audit decisions and reviewer traceability.
- Keeps bounded live validation evidence tied to the implementation history.

Cons of including commit 05:

- Adds generated JSON/CSV/Markdown noise.
- May include bulky live validation artifacts and local-only path details.
- Makes future diffs harder to review.

## Do Not Stage By Default

Manifest: `release_manifests/do_not_stage_local_only_20260525.txt`

Default local-only items include `PROJECT_MEMORY.md` and shadow review packets. These are useful operational context but are not recommended for the runtime release commit set.

## Defer To Separate Checkpoint

Manifest: `release_manifests/unrelated_or_defer_to_separate_checkpoint_20260525.txt`

This bucket contains earlier donor/sidecar work such as indexer, Polymarket protocol/ledger, shadow metrics, microstructure/trader-profile sidecars, and related tests/fixtures/tools. They should not be staged into this Side/Outcome/Event Forensic release unless the owner explicitly opens a separate checkpoint for them.

## Force-Add Required Ignored Files

Manifest: `release_manifests/force_add_required_ignored_files_20260525.txt`

Ignored files in docs/RFC/report/evidence buckets require explicit force-add if the owner chooses to commit them. This plan does not run `git add`.

## Recommended Commit Strategy

Preferred: four reviewable commits plus optional evidence kept local.

1. Commit 01: Runtime core Side/Outcome scanner/archive/browser work.
2. Commit 02: Event Forensic weak-history review-bucket demotion.
3. Commit 03: Offline benchmark/validation tooling and fixtures.
4. Commit 04: RFCs, readiness docs, and packaging manifests.
5. Commit 05: generated evidence only if the owner explicitly wants it.

Fallback: combine commit 01 and commit 02 if `app/event_forensic.py` cannot be hunk-split safely. Combining them is cleaner than making an intermediate commit that does not pass focused tests.

## Verification State

This packaging campaign did not rerun the full suite because it did not change runtime or tests. The prior release readiness state recorded a full suite of 936 OK after the weak-history demotion implementation.

For the next manual staging pass, use `release_manifests/packaging_verification_commands_20260525.md`.

## Final Recommendation

Decision: `ready_for_manual_split_staging_review`.

Do not stage automatically. Review the manifests, decide whether to combine commit 01 and 02, decide whether generated evidence belongs in git, then stage manually from the relevant manifest files.
