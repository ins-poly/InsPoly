# InsPoly RC V4 PR Reviewer Risk Audit - 2026-05-28

## Summary

PR #1 is reviewable but large. The highest risks are not a single failing check; they are reviewer scope, report-writer compatibility, sidecar/runtime boundary confusion, and packaging artifacts in the diff.

## Highest-Risk Code Areas

| Area | Risk | Review focus |
| --- | --- | --- |
| Report writers | Optional pointer path could affect saved report shape if not absent-safe. | Confirm `indexerWarehousePointer` is absent by default and only attached after validation. |
| Browser loaders | Browser could accidentally treat pointer metadata as UI payload. | Confirm no browser UI panel, sorting, filtering, or payload behavior changed for W4. |
| Side/outcome semantics | YES/NO economics are central to scanner/archive/Event Forensic correctness. | Review normalization tests and old raw-field preservation. |
| Event Forensic scope/demotion | Selected-market vs whole-event and weak-history demotion are behavior-sensitive. | Review scope metadata, demotion tests, and export preservation. |
| Sidecar indexer/warehouse | Large sidecar toolchain can be mistaken for production integration. | Confirm tools remain local/manual/no-network where intended and not imported into production runtime paths. |

## Largest File Groups

- Docs and compact validation outputs dominate the diff.
- Tests and fixtures are large because RC V4 accumulated benchmark, browser, Event Forensic, sidecar, and warehouse coverage.
- Runtime code changes are concentrated in `app/` and should be reviewed around report compatibility, browser offline boot, side/outcome, Event Forensic, and sidecar helper boundaries.

## Packaging And Local-Only Artifact Risk

Current campaign did not stage local-only artifacts. However, the PR history includes 10 tracked files under `release_manifests/` and 4 files under `phase3_capital_review_packets/`.

Reviewer action: decide whether those historical packaging/review artifacts are acceptable in the PR before marking it ready. If not, request a separate packaging cleanup commit rather than mixing deletion into this review packet.

Privacy hygiene update: this review pass scanned the PR diff for direct local user paths and common secret/token patterns. No private-key blocks or common hosted-service tokens were found. Committed `<local-user-home>` path strings in docs/compact outputs were redacted to neutral placeholders before this review packet was pushed.

## What Reviewers Should Inspect First

1. `docs/inspoly_rc_v4_github_release_overview_20260528.md`
2. `docs/inspoly_rc_v4_reviewer_guide_20260528.md`
3. `app/report_pointer.py`
4. `tests/test_indexer_report_pointer.py`
5. `tests/test_app_workflow_contracts.py`
6. `tests/test_event_forensic_scope_semantics.py`
7. `app/scanner.py`, `app/archive_scanner.py`, and `app/event_forensic.py` report writer diffs
8. Sidecar warehouse tools under `tools/indexer_warehouse_*.py`
9. Browser offline assets and provenance
10. `release_manifests/` and `phase3_capital_review_packets/` packaging artifacts

## Review Decision

The PR has strong local validation evidence but should remain Draft until a human reviewer accepts the packaging scope and the owner decides how to handle absent GitHub CI.
