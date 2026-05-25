# InsPoly Post-Side/Outcome Strategic State

- Date: 2026-05-22
- Scope: offline strategic reconciliation after Side/Outcome Phase 2 and Phase 4 runtime stabilization
- Runtime implementation in this step: false
- Network/RPC used: false
- Commit/push/staging: false

## Machine-Readable Snapshot

```json
{
  "phase2_model_probability": "phase2_stable",
  "phase4_cluster_direction": "phase4_stable",
  "phase3_capital_at_risk": "keep_phase3_blocked",
  "scoring_weights_thresholds": "blocked_without_explicit_approval",
  "direct_strong_risk_her_funding_candidate_admission": "blocked_without_explicit_approval",
  "storage_schema": "unchanged",
  "live_rpc_network_indexing": "blocked_without_operator_approval",
  "ui_sorting_filtering": "blocked_without_user_approval",
  "next_validation_gate": "post_side_outcome_needs_live_rpc_validation"
}
```

## Completed

- Phase 1 additive Side/Outcome display/schema clarity:
  - raw token fields remain raw;
  - economic-side probability fields are additive;
  - browser copy distinguishes `Token price` from `Economic prob.`;
  - old reports remain absent-safe.
- Phase 2 runtime model-probability migration:
  - low-probability and near-certainty model checks use economic-side probability where side/outcome/price normalize safely;
  - Event Forensic later-correctness and winner-rank semantics are economic-side aware;
  - raw token display fields remain preserved.
- Phase 4 runtime cluster-direction migration:
  - scanner/archive/Event Forensic same-side/cluster grouping uses normalized economic direction where safe;
  - BUY YES and SELL NO group as `long_yes`;
  - BUY NO and SELL YES group as `long_no`.
- Release readiness and staging manifest:
  - commit scope is classified, but no staging/commit/push happened.

## Stable

- Phase 2 gate: `phase2_stable`.
- Phase 4 gate: `phase4_stable`.
- Full local unittest after Phase 4 stabilization: `871` tests OK.
- Latest offline replay found no unexpected source-level drift outside Phase 2/4 scope.

## Blocked

- Phase 3 capital-at-risk / max-loss normalization: `keep_phase3_blocked`.
- Any scoring weight or threshold changes.
- Direct Strong Risk, HER routing, funding eligibility, or candidate-admission changes.
- UI sorting/filtering behavior changes.
- Storage schema changes.
- Live/RPC/network/indexer/trading behavior.
- Saved report/artifact mutation.

## Safe Local Next Work

- Offline benchmark corpus curation from existing saved artifacts and fixtures.
- Static/replay validation of old report loading and side/outcome fallback behavior.
- Sidecar-only benchmark replay improvements.
- Archive visibility drift audits using local artifacts.
- Docs and tests that preserve current Phase 2/4 behavior and keep Phase 3 blocked.

## RPC/Operator Approval Required

- Live rerun for remembered Event Forensic weak-history / near-certainty cases.
- Whole-event replay for large completed events where current saved artifacts are insufficient.
- Any fresh Polymarket/Gamma/Data API validation beyond local saved artifacts.

## User Approval Required

- Phase 3 runtime capital-at-risk migration.
- Any model weight/threshold retuning.
- Direct Strong Risk/HER/funding/candidate-admission rule migration.
- UI sorting/filtering changes.
- Commit/staging policy for the broad local reform worktree.

## Backlog Items Reconciled After Phase 2/4

No longer current as open implementation blockers:

- "Migrate Side/Outcome model probability" is complete and stable.
- "Migrate Side/Outcome same-side cluster direction" is complete and stable.
- "Clarify entry chance/token price display" is complete for current browser/report surfaces.

More important after Phase 2/4:

- Verify weak-history near-certainty Event Forensic rankings using live or stable saved reruns.
- Keep Phase 3 capital-at-risk blocked until accounting evidence is strong enough.
- Curate known-case benchmark fixtures so future model migrations have analyst labels, not only heuristic drift counts.
- Preserve archive visibility drift monitoring because old/lossy archive rows remain risky for reinterpretation.
