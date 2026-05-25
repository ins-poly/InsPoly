# InsPoly Archive Completeness / Visibility Program

- Date: 2026-05-22
- Scope: archive completeness and visibility integrity after Side/Outcome reform
- Machine output: `validation_outputs/inspoly_archive_completeness_visibility_program_20260522.json`
- Runtime implementation in this program: false
- Network/RPC used: false
- Gate decision: `archive_visibility_monitoring_local_only`

## Current Evidence

Archive evidence is locally abundant but mixed in quality.

| Metric | Count |
|---|---:|
| archive artifacts discovered | 4,835 |
| artifacts selected for bounded audit | 120 |
| records loaded | 3,308 |
| evaluable records | 2,021 |
| lossy CSV rows without price | 1,284 |
| price missing or unknown rows | 1,287 |
| archive visibility doc drift rows | 0 |
| archive visibility changed by this program | false |

## Findings

- Archive artifacts can support local drift monitoring.
- Old/lossy archive CSV rows cannot safely be used for rescoring when side/outcome/price is incomplete.
- Archive visibility remains annotate-not-hide.
- Visibility annotation is separate from scoring and severity labels.
- Large archive trade CSVs are skipped by bounded audits and need chunked read-only monitoring if exact completeness is required.

## What Remains Blocked

- Archive visibility behavior changes.
- Candidate admission broadening.
- Rescoring from lossy old CSV rows.
- Browser sorting/filtering changes.

## Allowed Local Work

- Read-only chunked archive completeness audit.
- Documentation drift monitoring.
- Focused tests that preserve annotate-not-hide semantics.

## Approval Required

- Any archive visibility behavior change.
- Candidate admission changes.
- Live/RPC archive collection.

## Gate Decision

Decision: `archive_visibility_monitoring_local_only`.

Archive is safe for continued local monitoring, not behavior change.
