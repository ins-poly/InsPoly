# InsPoly Archive Visibility Monitoring V2

- Date: 2026-05-22
- Scope: local archive completeness and visibility monitoring
- Tool: `tools/archive_visibility_monitoring_v2.py`
- Machine output: `validation_outputs/archive_visibility_monitoring_v2_20260522.json`
- Runtime implementation: false
- Network/RPC used: false
- Archive visibility changed: false
- Gate decision: `archive_visibility_monitoring_v2_ready`

## Local Scan

| Metric | Count |
|---|---:|
| artifacts scanned | 220 |
| loadable artifacts | 214 |
| skipped too large | 6 |
| rows evaluated | 940 |
| real local artifact rows | 909 |
| synthetic fixture rows | 31 |
| visible / hard-evidence rows | 4 |
| secondary-review rows | 3 |
| legacy excluded rows | 1 |
| old/lossy rows | 12 |
| missing side rows | 921 |
| missing outcome rows | 921 |
| missing price rows | 924 |
| truncation marker rows | 1 |

## Findings

- Archive monitoring can stay local and read-only.
- Most bounded rows are old/lossy or lack side/outcome/price fields, so they must not be used for unsafe rescoring.
- Visibility remains annotate-not-hide.
- Large archive artifacts need chunked monitoring if exact completeness is required.

## Requires Approval

- Any archive visibility behavior change.
- Candidate admission changes.
- Live/RPC archive collection.

## Gate

Decision: `archive_visibility_monitoring_v2_ready`.
