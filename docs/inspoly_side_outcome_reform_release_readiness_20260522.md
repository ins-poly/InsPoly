# InsPoly Side/Outcome Reform Release Readiness

- Date: 2026-05-22
- Scope: release checkpoint and integration review only
- Runtime implementation in this step: false
- Commit/push in this step: false
- Readiness decision: `needs_cleanup_before_commit`

This checkpoint does not approve new model migrations. It records the state after the approved Phase 2 and Phase 4 runtime migrations, the sidecar evidence trail, and the staging decisions still required before a safe commit.

## Current Gate Ledger

| Phase | State | Evidence | Commit-readiness note |
|---|---|---|---|
| Phase 1 side/outcome display/schema clarity | completed | additive helper, labels, report/export fields, backward-compatibility tests | Runtime/display fields are additive and should be included if committing the reform. |
| Phase 2 RFC/audit | completed | `docs/inspoly_side_outcome_phase2_model_migration_rfc_20260522.md`, readiness and archive evidence audits | Evidence gate was raised only after archive fixtures/evidence. |
| Phase 2 runtime migration | stable | `docs/inspoly_side_outcome_phase2_runtime_migration_20260522.md`, post-migration stabilization report, full tests | Economic-side probability is now the approved model probability where side/outcome/price normalize safely. |
| Phase 3 capital-at-risk | blocked | `docs/inspoly_side_outcome_phase3_capital_at_risk_impact_audit_20260522.md` | Gate remains `keep_phase3_blocked`; do not reinterpret raw notional/exposure in this checkpoint. |
| Phase 4 RFC/audit | completed | `docs/inspoly_side_outcome_phase4_cluster_direction_rfc_20260522.md`, impact audit JSON/report | Evidence supported a bounded cluster-direction implementation. |
| Phase 4 runtime migration | stable | `docs/inspoly_side_outcome_phase4_runtime_migration_20260522.md`, post-migration stabilization report, full tests | Normalized same-side/cluster grouping is stable; no Phase 3 behavior was bundled. |

Remaining blocked items:

- Phase 3 capital-at-risk / max-loss normalization.
- Scoring weight or threshold changes.
- Direct Strong Risk, HER, funding eligibility, or candidate-admission rule changes.
- UI sorting/filtering behavior changes.
- Storage schema changes.
- Live/RPC/network indexing or trading behavior.
- Saved report/artifact mutation.

## Worktree Inventory

Visible git status before this checkpoint:

| Category | Count | Notes |
|---|---:|---|
| Modified tracked files | 11 | Runtime/browser/tests changed by Side/Outcome Phase 1/2/4 work. |
| Visible untracked files | 188 | New helpers, sidecar tools, fixtures, tests, and review packets. |
| Ignored docs files under `docs/` | 56 total docs files in local tree | `docs/*` is ignored by `.gitignore`, so release docs require an explicit staging decision. |
| Ignored side-outcome audit JSON files | 10 | `side_outcome_audits/` is ignored; these are evidence outputs, not runtime dependencies. |
| Side/outcome review packet files | 6 visible untracked files | Useful analyst review artifacts, but generated and potentially bulky. |
| Shadow review packet files | 58 visible untracked files | Generated sidecar preview artifacts from the donor/sidecar campaign. |

Tracked modified files:

- `app/archive_scanner.py`
- `app/browser_desktop.py`
- `app/browser_event_forensic_ui.html`
- `app/browser_ui.html`
- `app/event_forensic.py`
- `app/scanner.py`
- `tests/test_app_workflow_contracts.py`
- `tests/test_benchmark_schema_compatibility.py`
- `tests/test_cross_mode_scoring_contract.py`
- `tests/test_scanner_patterns.py`
- `tests/test_side_outcome_price_normalization_audit.py`

Key visible untracked groups:

- Production/runtime helper: `app/side_outcome.py`
- Sidecar/helpers: `app/indexer/`, `app/polymarket_protocol.py`, `app/polymarket_ledger.py`, `app/shadow_metrics.py`, `app/microstructure_context.py`, `app/trader_profile_context.py`, `app/benchmark_cases.py`
- Sidecar tools: `tools/side_outcome_*`, `tools/shadow_*`, `tools/indexer_fixture_dry_run.py`, `tools/validate_polymarket_ledger_against_artifacts.py`, and related evaluator/render/audit tools
- Tests and fixtures: new protocol, ledger, shadow, side/outcome Phase 2/3/4, indexer, benchmark, and preview fixtures/tests
- Generated review outputs: `shadow_review_packets/`, `side_outcome_review_packets/`

No unrelated pre-existing changes were identified with enough confidence to separate from the current donor/sidecar/side-outcome campaign. The broad worktree should be treated as one campaign checkpoint unless the user requests a narrower commit split.

## Runtime Change Summary

### `app/side_outcome.py`

What changed:

- Adds the central source of truth for raw-token/economic-side normalization.
- Provides `normalize_side_outcome()` for:
  - raw token outcome;
  - raw order side;
  - raw token price;
  - economic side;
  - economic-side probability;
  - normalized economic direction;
  - normalization status and fallback reason.
- Provides `normalize_cluster_direction()` for Phase 4 normalized same-side grouping.

What is preserved:

- Unknown/malformed side, outcome, or price stays `unknown`; missing values are not coerced to zero.
- Raw token price and raw order side/outcome stay explicit display fields.
- Decimal parsing preserves probability semantics including percent-form inputs.

Tests covering it:

- `tests/test_side_outcome_normalization.py`
- `tests/test_side_outcome_price_normalization_audit.py`
- `tests/test_side_outcome_phase2_model_contract.py`
- `tests/test_side_outcome_phase4_cluster_direction_audit.py`

### `app/scanner.py`

What changed:

- Phase 2: low-probability conviction, near-certainty checks, uncertainty, repricing-quality high-price checks, and resolution-gap probability checks now use economic-side `model_probability` when normalization is safe.
- Phase 2: raw metrics gained additive provenance fields such as `model_probability`, `model_probability_basis`, `model_economic_direction`, and `side_outcome_normalization_status`.
- Phase 4: same-side windows, pre-admission direction hints, split-wallet grouping, proxy cohorts, and coordinated-sizing group keys use normalized cluster direction when safe.

What is preserved:

- Scoring weights and thresholds are unchanged.
- Raw fields such as `price_implied_probability`, `economic_direction`, side/outcome/price, and `capital_at_risk_usdc` remain available.
- Phase 3 capital-at-risk still uses the existing raw notional/exposure semantics.
- Strong Risk, HER, funding eligibility, and candidate admission were not directly rewritten.

Fallback rules:

- If side/outcome/price cannot be normalized, model probability falls back to raw token price and cluster grouping does not force normalized direction.

Tests covering it:

- `tests/test_scanner_patterns.py`
- `tests/test_cross_mode_scoring_contract.py`
- `tests/test_side_outcome_phase2_model_contract.py`
- `tests/test_side_outcome_phase2_post_migration_drift_audit.py`
- `tests/test_side_outcome_phase4_post_migration_drift_audit.py`

### `app/archive_scanner.py`

What changed:

- Archive trade rows and flagged CSV exports now include additive raw/economic side-outcome and cluster-direction provenance fields.
- Archive rows can expose Phase 1/2/4 context without renaming old columns.

What is preserved:

- Existing archive JSON/CSV fields remain present.
- Lossy old archive rows without enough side/outcome/price evidence are not safe rescoring sources.
- Archive visibility/excluded semantics were not changed.

Tests covering it:

- `tests/test_side_outcome_archive_evidence_audit.py`
- `tests/test_app_workflow_contracts.py`
- `tests/test_benchmark_schema_compatibility.py`

### `app/event_forensic.py`

What changed:

- Phase 2: `laterWon`, winning-entry ranks, low-probability winner, near-certainty checks, and wallet hard-evidence attribution use economic-side probability/side where safe.
- Phase 2/4: suspicious trade payloads and CSV exports carry additive raw/economic/cluster provenance fields.
- Phase 4: timing clusters use `clusterDirection` when `clusterNormalizationStatus` is normalized, with conservative raw side/outcome fallback otherwise.
- Narrative display clarifies token price and economic-side probability.

What is preserved:

- Event Forensic weights, overlay formula, and thresholds are unchanged.
- Raw token/display fields remain in payloads and exports.
- Old artifact loading remains absent-safe.
- Sorting/filter behavior is not redesigned.

Tests covering it:

- `tests/test_event_forensic_review_artifacts.py`
- `tests/test_side_outcome_phase2_model_contract.py`
- `tests/test_side_outcome_phase2_post_migration_drift_audit.py`
- `tests/test_side_outcome_phase4_post_migration_drift_audit.py`

## Generated Artifact Review

Recommended `should commit` if this is one consolidated reform checkpoint:

- Runtime/source files required by the implemented behavior:
  - `app/side_outcome.py`
  - `app/scanner.py`
  - `app/archive_scanner.py`
  - `app/event_forensic.py`
  - browser label/payload compatibility updates in `app/browser_desktop.py`, `app/browser_ui.html`, `app/browser_event_forensic_ui.html`
- Focused tests and fixtures that make Phase 1/2/3/4 contracts executable.
- Sidecar audit tools that are needed to reproduce gate decisions:
  - `tools/side_outcome_phase2_impact_audit.py`
  - `tools/side_outcome_archive_evidence_audit.py`
  - `tools/side_outcome_phase2_post_migration_drift_audit.py`
  - `tools/side_outcome_phase3_capital_at_risk_audit.py`
  - `tools/side_outcome_phase4_cluster_direction_audit.py`
  - `tools/side_outcome_phase4_post_migration_drift_audit.py`
- RFC/readiness/stabilization docs if audit traceability should live in git. Because `docs/*` is ignored, these require explicit force-add or `.gitignore` adjustment.

Recommended `should keep local only` unless the user wants a full evidence bundle:

- `side_outcome_review_packets/phase2_post_migration_sensitive_cases_20260522/`
- `side_outcome_review_packets/phase4_post_migration_sensitive_merge_groups_20260522/`
- `shadow_review_packets/`

Recommended `needs user decision`:

- `side_outcome_audits/*.json`: useful machine-readable evidence, but generated and currently ignored. Commit only selected final JSONs if reproducibility matters more than repository size/noise.
- Shadow/donor sidecar campaign files: they are test-covered and sidecar-only, but they are broader than Side/Outcome runtime readiness. They can be committed as a separate sidecar checkpoint or included in one large reform checkpoint.
- `.gitignore`: current ignore rules hide `docs/*`, `PROJECT_MEMORY.md`, and `side_outcome_audits/`. Decide whether release docs/audit JSON should stay ignored and be force-added selectively, or whether a narrower allow-list should be added.

Recommended `maybe .gitignore`:

- Review packet directories, if not meant as source artifacts.
- Timestamped generated audit/review outputs beyond selected final summaries.

No files were deleted or mutated by this review.

## Regression Matrix

| Surface | Verification status | Notes |
|---|---|---|
| Recent Scanner model probability | covered | Economic-side probability used where safe; raw token fields preserved. |
| Recent Scanner cluster grouping | covered | Normalized cluster direction used for same-side grouping; Phase 3 exposure not changed. |
| Archive exports | covered | Additive fields only; old columns retained. |
| Event Forensic later correctness | covered | Economic side used for winner semantics; score weights unchanged. |
| Event Forensic timing clusters | covered | Uses normalized cluster direction only when provenance is safe. |
| Browser display compatibility | covered | Labels distinguish token price from economic probability; entry-price sorting remains raw-token. |
| Old report loading | covered | Absent-safe paths and fallback labels preserved. |
| Cross-mode scoring contract | covered | Current model deltas are intentional Phase 2/4 behavior, not weight/threshold changes. |
| Phase 3 capital-at-risk | blocked | Direct scan confirms `_capital_at_risk_usdc()` does not call side/outcome or cluster normalization. |
| Storage schema | unchanged | Direct scan found no side/outcome/cluster schema markers in `app/storage.py`. |
| Live/RPC/network | unchanged | Direct scan found no side/outcome/cluster changes in `app/polymarket.py`. |

## Verification Run

Commands run for this checkpoint:

- Changed/new Python compile check: `84` Python files compiled successfully.
- Focused side/outcome Phase 2/3/4 tests: `67` tests passed.
- Cross-mode/scanner/archive/Event Forensic/browser contract tests: `224` tests passed.
- Full unittest discovery: `871` tests passed.
- `git diff --check`: passed.

Observed non-blocking noise:

- Existing sqlite `ResourceWarning` messages during tests.
- Existing validation-interrupted terminal failure artifact message from the validation-corpus test path.

Direct scans:

- `phase3_capital_helper_uses_side_outcome=false`
- `storage_cluster_schema_marker=false`
- `polymarket_live_marker=false`
- `browser_sort_filter_cluster_marker=false`
- `browser_entry_sort_still_raw_function=true`

No whitespace issues were found after writing this checkpoint and updating `PROJECT_MEMORY.md`.

## Commit Plan, No Commit

Suggested commit title:

`Stabilize side/outcome economic semantics and sidecar guardrails`

Suggested commit body:

```
Implement side/outcome raw-token vs economic-side normalization guardrails.

- add central side/outcome normalization and normalized cluster direction helpers
- migrate approved Phase 2 model probability semantics to economic-side probability
- migrate approved Phase 4 same-side/cluster grouping to normalized economic direction
- preserve raw token display fields, old report compatibility, thresholds, and weights
- keep Phase 3 capital-at-risk normalization blocked
- add sidecar audits, fixtures, docs, and regression tests for Phase 2/3/4 gates

Verification:
- py_compile changed/new Python files
- focused side/outcome Phase 2/3/4 suites
- cross-mode, scanner, archive, Event Forensic, and browser compatibility tests
- full unittest discovery
```

Files that should likely be staged for a consolidated checkpoint:

- Runtime/display:
  - `app/side_outcome.py`
  - `app/scanner.py`
  - `app/archive_scanner.py`
  - `app/event_forensic.py`
  - `app/browser_desktop.py`
  - `app/browser_ui.html`
  - `app/browser_event_forensic_ui.html`
- Tests/fixtures:
  - Side/outcome Phase 1/2/3/4 tests and fixtures.
  - Updated scanner/archive/Event Forensic/browser contract tests.
- Reproducibility tools:
  - Side/outcome audit tools for Phase 2/3/4.
- Docs:
  - Side/outcome RFC/audit/runtime/stabilization docs, including this readiness checkpoint, if the audit trail should be versioned.

Files that probably should not be staged without an explicit evidence-bundle decision:

- `shadow_review_packets/`
- `side_outcome_review_packets/`
- all timestamped or large generated audit JSON outputs except selected final evidence files
- `PROJECT_MEMORY.md`, unless the repository intentionally versions local agent memory

Risks to mention in a PR:

- Phase 2 intentionally changes low-probability/near-certainty interpretation for SELL Yes/No via economic-side probability.
- Phase 4 intentionally changes same-side cluster grouping for BUY/SELL expressions that are economically equivalent.
- Phase 3 remains blocked; capital-at-risk still uses existing raw notional/exposure semantics.
- Broad sidecar/donor files may be better reviewed as a separate commit if the maintainer wants smaller review units.

Rollback strategy:

- Revert runtime files `app/side_outcome.py`, `app/scanner.py`, `app/archive_scanner.py`, `app/event_forensic.py`, and browser label/payload updates to return to pre-Phase-1/2/4 behavior.
- Keep sidecar audit docs/tools available for diff diagnosis even if runtime changes are reverted.
- Do not mutate saved reports during rollback; old reports remain absent-safe because report-key changes are additive.

## Final Decision

Decision: `needs_cleanup_before_commit`.

The code/test state is verification-clean, but the worktree is too broad for an automatic commit decision. Before committing, choose whether this should be:

1. one consolidated reform checkpoint including runtime, tests, docs, fixtures, and selected audit tools; or
2. split into commits for sidecar infrastructure, shadow campaign evidence, Side/Outcome runtime, and generated evidence packets.

No commit or push was performed.
