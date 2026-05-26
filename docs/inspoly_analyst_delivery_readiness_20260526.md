# InsPoly Analyst Delivery Readiness

Date: 2026-05-26

Overall gate: `analyst_delivery_ready_local`

Replay gate: `replay_persistence_rfc_ready_no_runtime`

Browser offline gate: `browser_offline_assets_need_product_decision`

Runtime/UI patch in this campaign: `false`

Network/RPC used: `false`

## Executive Summary

The local analyst delivery surface is ready for use with current local reports, validation outputs, sidecar review packets, and browser UIs when browser CDN assets are available. The important model/runtime directions are explicit:

- Side/Outcome Phase 2/4 semantics are implemented and stable.
- Event Forensic weak-history review demotion is implemented.
- Event Forensic selected-market vs whole-event scope semantics are visible in new reports and the Event Forensic browser UI.
- Event Forensic pagination/provider uncertainty is documented and warning-bearing.
- Phase 3 capital-at-risk runtime is blocked and sidecar-only.
- Replay snapshots and replay schedules are safe sidecars, not storage-backed persistence.

No runtime, scoring, gate, storage, pagination, or UI sorting/filtering changes were made in this campaign.

## Analyst Surfaces

| Surface | Current readiness | Analyst can trust | Limits |
|---|---|---|---|
| Browser main UI | usable with CDN runtime assets | local scanner/archive reports, Side/Outcome labels, truncation diagnostics | strict offline boot blocked by missing assets |
| Event Forensic browser UI | usable with CDN runtime assets | scope semantics, weak-history caveats, pagination warnings, raw/economic labels | old reports may lack new additive fields and rely on fallback |
| Report JSON/CSV/Markdown exports | ready with compatibility caveats | raw token fields, economic-side fields, review buckets, warnings, full CSV exports where written | old reports remain partial/legacy; Phase 3 capital remains raw/blocked |
| Replay snapshot sidecar | ready for local validation | candidate IDs, scope, timing, score/review metadata from already-collected reports | no live rerun, no scoring engine, no persistence scheduler |
| Replay schedule sidecar | ready as plan-only | planned `initial`, `+1h`, `+4h`, `+24h` stages and timing-budget metadata | no background scheduling or storage mutation |
| Review packets | useful local evidence | human-readable sidecar packets for specific investigations | generated/local-only by default |
| Shadow/context previews | useful local sidecar context | offline evaluation and preview only | no report-copying or scorer integration approved |
| Validation outputs | useful machine-readable evidence | compact committed summaries and local raw evidence | bulky raw outputs remain local-only |

## Warning And Metadata Audit

| Topic | Current analyst visibility | Gap classification | Decision |
|---|---|---|---|
| Selected-market vs whole-event scope | Event Forensic report metadata and browser summary show analysis scope, primary scoring scope, sibling context, and scope explanation | acceptable for new reports; old reports fallback | no patch |
| Context-only sibling markets | Event Forensic UI copy states related/sibling activity is context-only for selected-market reports | acceptable | no patch |
| Pagination/truncation risk | Event Forensic report warnings, summary counts, progress metrics, and browser narrative mention pagination caps | acceptable; provider semantics remain docs/RFC-backed | no runtime patch |
| Weak-history near-certainty demotion | Additive fields and Event Forensic browser copy expose reducer/demotion caveats and review bucket state | acceptable | no patch |
| Raw token vs economic probability | Browser main UI and Event Forensic UI show raw token label and economic-side probability label | acceptable | no patch |
| Phase 3 capital blocked/sidecar-only | Visible in docs, benchmarks, and sidecar outputs; not embedded in normal analyst UI | acceptable for now because runtime Phase 3 is not active | report/UI field should wait for a Phase 3 sidecar embedding decision |
| Provider/query semantics uncertainty | Current docs and report warnings identify truncation/provider uncertainty; UI does not expose the full RFC | acceptable; detailed RFC is operator-facing | no patch |
| Replay persistence status | Visible in docs and sidecar JSON; not embedded in browser UI | acceptable for sidecar-only stage | report/UI embedding needs future product decision |

## Replay Readiness

Replay sidecars are safe now for local analyst validation:

- snapshots are built from already-collected report data;
- old reports load absent-safe with quality notes;
- restricted secret-like keys are detected;
- schedule plans are planned-only;
- no live/RPC, storage mutation, background scheduler, scoring, gates, or exports change.

Replay is not production persistence:

- snapshots are machine-readable, not a polished analyst report;
- scheduled replay stages are not automatically executed;
- storage-backed replay requires a separate RFC/migration;
- report-embedded replay metadata requires product approval.

Decision: `replay_persistence_rfc_ready_no_runtime`.

## Browser Offline Readiness

Browser offline assets remain product-gated:

- 2 browser HTML files inspect as network-dependent for boot;
- 6 runtime-required local assets are missing;
- Google Fonts are remote;
- no assets were downloaded or vendored.

Decision: `browser_offline_assets_need_product_decision`.

Strict offline release should wait for an approved local asset patch. The current local browser workflow remains usable when CDN runtime assets are reachable.

## What Analysts Can Trust Now

Analysts can trust:

- Side/Outcome raw token vs economic-side labels in current report outputs.
- Event Forensic review buckets, including weak-history demotion metadata.
- Event Forensic selected-market vs whole-event scope labels in new reports.
- Pagination/truncation warnings as evidence that a report may be partial.
- Replay snapshots as sidecar snapshots of already-collected report data.
- Phase 3 sidecar outputs as analyst-only source-quality evidence, not runtime capital scoring.

Analysts should not infer:

- selected-market reports are whole-event complete;
- truncated reports are complete;
- replay snapshots are fresh reruns;
- Phase 3 economic max-loss is active in scanner/archive/Event Forensic runtime;
- browser offline boot is guaranteed without vendored assets.

## Blocked Promotions

| Promotion | Blocker |
|---|---|
| Strict offline browser release | missing local React/ReactDOM/Babel/font assets and product asset decision |
| Storage-backed replay persistence | storage schema/RFC/product approval required |
| Automatic replay scheduling | operator approval, live/RPC bounds, and persistence design required |
| Production pagination expansion | provider/query semantics and material new-row evidence insufficient |
| Phase 3 capital runtime | direct sensitive SELL evidence/source-field blockers remain |
| Push/PR | user-gated |

## Recommended Next Campaign

The next highest-value local analyst-delivery campaign is a bounded browser offline asset implementation only after the owner approves local asset vendoring. Without that product decision, the better next step is replay persistence design for report-embedded metadata, still RFC-only and without storage migration.

## Final Decision

Overall gate: `analyst_delivery_ready_local`.

The local analyst workflow is sufficiently documented and safe for local use. Remaining blockers are product/operator decisions, not hidden runtime tasks.
