# Archive/Event Completeness Audit

Date: 2026-05-25

Gate: `archive_event_completeness_local_ready`

This is a read-only local audit. It is not approval for pagination runtime changes, candidate-admission changes, ranking changes, scoring changes, or broader live collection.

## What Was Inspected

- Local archive report JSON outputs.
- Local Event Forensic report JSON outputs.
- Bounded report-like validation outputs and fixtures.
- Raw event bundles were intentionally skipped.

Machine-readable output:

- `validation_outputs/archive_event_completeness_audit_20260525.json`

## Local Results

- Reports evaluated: 78
- Archive reports: 39
- Event Forensic reports: 39
- Complete local reports: 36
- Explicitly truncated reports: 20
- Likely truncated without marker: 0
- Unknown legacy reports: 22
- Candidate-admission risk reports from truncation markers: 20
- Event Forensic ranking-risk reports from truncation markers: 3

## Interpretation

The local reports already carry useful truncation markers in the sampled archive/Event Forensic outputs. The main local risk is not a missing marker bug; it is that some reports are explicitly bounded/truncated and therefore cannot be treated as complete forensic evidence.

Legacy Event Forensic reports without current metadata remain `unknown_legacy`. They must not be rescored or reinterpreted as complete unless regenerated or validated with bounded live/RPC.

## Preserved Invariants

- No saved reports were mutated.
- No scanner/archive/Event Forensic runtime code changed.
- No scoring weights, thresholds, Strong Risk/HER/funding/candidate gates, storage schema, or UI behavior changed.
- Selected-market reports are not marked incomplete merely because sibling markets exist.

## Next Gate

No local deterministic marker bug was found. Deeper completeness validation requires a bounded operator-approved measurement or pagination run, not a broad crawler.
