# Indexer W4 Report Pointer Product Decision - 2026-05-27

## Decision

Gate: `indexer_w4_pointer_metadata_rfc_ready`

W4 pointer metadata is ready for a future implementation RFC, but implementation is not approved in this campaign.

## Product Context

W3 can answer analyst questions from compact sidecar registry metadata, but an analyst opening a scanner/archive/Event Forensic report has no report-level breadcrumb to the relevant local sidecar warehouse artifact. W4 would address discoverability only.

## Options Compared

| Option | Decision | Reason |
| --- | --- | --- |
| Keep W3 sidecar-only | Safe fallback | Lowest risk and remains the current runtime behavior. |
| Top-level report pointer metadata only | RFC-ready | Additive and absent-safe if limited to metadata. It can point to W2/W3 artifacts without copying metrics. |
| Browser-visible pointer only | Blocked for now | Requires UI/product approval and old-report copy decisions. |
| Copied warehouse metrics | Rejected | Would make advisory sidecar evidence look like report evidence and risks scoring/report confusion. |
| Row-level sidecar context | Rejected | Too close to report embedding and could imply row-level verdict support that W3 does not provide. |

## Why Pointer Metadata Is RFC-Ready

- Current report writers already persist plain JSON objects.
- Current loaders and browser payload builders tolerate absent fields and use known keys.
- Old reports do not require the future field.
- W3 artifacts are compact, advisory-only, sidecar-only, and explicitly not scoring/report integrated.
- A pointer can be rollback-safe because it would be one optional top-level object in newly generated reports only.

## Why Implementation Remains Blocked

Implementation would still touch report schema boundaries. A future campaign must prove:

- old reports load the same when the pointer is absent;
- new reports include only the pointer object;
- browser payloads do not sort, filter, label, rank, or visually elevate rows based on the pointer;
- no warehouse metrics are copied into reports;
- no sidecar query tool is imported into scanner/archive/Event Forensic/browser runtime paths;
- rollback removes pointer emission without mutating saved historical reports.

## Required Future Product Framing

If implemented later, the pointer must say:

- sidecar-only;
- advisory-only;
- local paths may be machine-specific;
- registry data may be stale;
- no scoring effect;
- no routing effect;
- no metrics copied;
- no UI panel required.

## Final Decision

Proceed only to static schema and future implementation packet. Keep current runtime behavior W3 sidecar-only until a separate product-approved W4 implementation campaign exists.
