# Indexer Warehouse Risk Register - 2026-05-27

## Summary

Overall RFC risk: medium, because warehouse work touches persistence, operator workflow, and live public data. Current implementation risk is low because this campaign is RFC-only.

## Risks

| Risk | Current State | Mitigation | Status |
| --- | --- | --- | --- |
| Provider drift | Observed as collection-policy/provider drift, not storage drift. | Keep scoped compare and classify provider drift separately. | Managed for RFC. |
| Target ambiguity | Failed Iran slug proved event-family mismatch risk. | Use target registry and resolver preflight. | Managed for current set. |
| Cap starvation | Aggregate collection starved two targets. | Per-target cap now proven for three targets. | Managed for current set. |
| Malformed `raw_json` | Current audits show 0 malformed rows. | Readiness audit blocks malformed raw JSON. | Managed. |
| Duplicate rows | Current audits show 0 duplicate indicators. | Stable IDs and duplicate audit checks. | Managed. |
| Cursor corruption | Current cursors are aggregate and clean. | Future RFC must design per-condition cursor policy. | Open. |
| Local DB growth | Only small bounded DBs proven. | Retention caps and local deletion policy needed. | Open. |
| False confidence from sidecar data | Sidecar data can look product-ready before integration is safe. | Keep sidecar-only labels and no scoring/report use. | Managed by gate. |
| Accidental production import | Current scans/tests show sidecar isolation. | Require import isolation scan in every stage. | Managed. |
| Report/UI confusion | Pointer/report integration not approved. | Keep packets sidecar-only; future pointer RFC required. | Managed by gate. |
| Stale data | Old DBs can age after run. | Readiness audit includes stale cursor classification. | Managed for review, open for retention. |
| Retention/privacy concerns | Raw DBs include wallets/trades and stay local-only. | Raw DB local-only policy plus deletion guidance. | Open. |
| Operator error | Wrong slug/cap/output can widen scope. | Config validator, exact target registry, fresh output paths. | Managed for bounded runs. |
| Future daemon/scheduler risk | Not implemented and high-risk. | Keep W5 separately approval-gated. | Blocked. |

## Highest-Risk Future Decisions

1. Whether to add per-condition cursor schema or encode it in existing cursor keys.
2. Whether to allow append-mode warehouse DBs instead of fresh run DBs.
3. Whether analyst report pointers are worth the compatibility risk.
4. Whether scheduling is worth the lifecycle/disk/operator-control risk.

## Required Review Before W0

Before any W0 implementation, review:

- sidecar schema compatibility;
- old DB read behavior;
- retention and deletion policy;
- import isolation scan;
- readiness/compare gate definitions;
- exact no-production-runtime boundary.
