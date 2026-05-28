# InsPoly Sidecar Context Analyst Integration RFC

Date: 2026-05-27 EEST

Gate: `sidecar_context_report_pointer_rfc_ready`

## Options

| Option | Status | Tradeoff |
| --- | --- | --- |
| Keep all context sidecar-only | Current final path | Lowest regression and confusion risk; analysts must open sidecar outputs manually. |
| Manual browser-openable preview index | Not implemented now | Existing sidecar tools already write previews and packet indexes. |
| Optional top-level report pointer to sidecar artifacts | RFC-ready, not approved | Could improve traceability without copying metrics, but still changes report shape. |
| Tiny analyst-only UI panel reading selected sidecar files | Needs product approval | Better UX, but risks treating advisory context as verdicts and requires UI design/testing. |

## Why Prior Report-Copying Was Blocked

The post-9E sidecar campaign selected `keep_sidecar_only`: useful advisory metric density was low, duplicate/confusion risk remained high, missing microstructure snapshots dominated unknowns, and `missing_token_id` required a report-schema gate. Copying metrics into production reports would make incomplete context look more authoritative than it is.

## Narrow Future Report Pointer Shape

If approved later, a pointer-only report field should contain only:

- sidecar artifact type;
- local relative path or artifact id;
- generated timestamp;
- advisory scope label;
- no copied metrics;
- no scoring/routing effect.

Old reports must remain absent-safe. New reports must clearly distinguish sidecar context from verdicts.

## Rollback

For a future pointer-only implementation, rollback would remove the additive pointer field and leave sidecar artifacts untouched. For any UI panel, rollback would remove the panel and preserve report loading.

## Decision

No report-copying or UI panel is implemented by this campaign. The only safe future product question is whether a pointer-only report metadata RFC should be approved.
