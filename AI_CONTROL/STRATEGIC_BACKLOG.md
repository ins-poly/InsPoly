# Strategic Backlog

Last updated: 2026-05-28 EEST.

## Must Preserve
- Do not change scoring/gates/visibility semantics without explicit approval.
- Do not stage/push local-only memory, generated evidence, or review packets without explicit approval.
- Keep sidecar helpers out of production runtime paths.
- Keep funding `unknown` distinct from `none`.
- Keep selected-market vs whole-event semantics explicit.
- Keep Strategic Operating System autonomy bounded by approval gates.

## Highest-Leverage Next Work
- RC V4 has been merged into `main` and post-merge verified. Current gate: `rc_v4_merged_post_merge_verified`. Future work should start from updated `main`; do not continue feature work on `codex/inspoly-local-release-candidate-v4` unless investigating the old PR branch specifically.
- Next release-management choices: keep the merged branch briefly for rollback reference or delete it after an explicit branch-cleanup decision; optionally prepare release notes/tag if the owner wants a formal GitHub release.
- For the remaining donor-derived integration branches, use `docs/inspoly_donor_remaining_three_branch_decision_20260527.md` as the current gate reference. Final combined gate: `three_branch_execplan_no_safe_runtime_changes`.
- For the next post-donor approval layer, use `docs/inspoly_operator_approval_readiness_campaign_summary_20260527.md` as the current gate reference. Final combined gate: `operator_approval_readiness_packets_ready_no_runtime`.
- If indexer work continues, use the bounded live-indexer approval packet, config validator, manual sidecar runner, first-run report, repeat-run hardening RFC, DB compare tool, same-slug repeat probe report, multi-target reports, target registry, resolver preflight, scoped compare outputs, repeatability/collection campaign, per-target collection hardening campaign, warehouse RFC packet, W0 contract/readiness packet, W1 manual-command packet, W2 registry/retention packet, W3 analyst query packet, and RC V4 W4 pointer implementation packet first. Current gate: `indexer_w4_pointer_metadata_implemented_no_ui_no_metrics`. The next safe indexer step is not another local completion campaign; it is either owner-approved push/PR or a separately approved W4 visible UI/product expansion, still with no copied metrics, no row-level sidecar context, no scoring/gate effect, no live ingestion, no warehouse writer/copy behavior, no storage migration, and no scheduler/background mode unless separately approved.
- If analyst context work continues, decide whether pointer-only report metadata is product-approved; current decision remains `sidecar_report_pointer_keep_sidecar_only`, and metrics must not be copied into reports.
- If pUSD/CLOB collateral work continues, reconcile adapter address discrepancies and define pUSD/wrap/exchange-fill tracing policy before any funding runtime or Phase 3 runtime RFC.
- PR `#1` is now closed and merged: https://github.com/ins-poly/InsPoly/pull/1. Use `docs/inspoly_rc_v4_post_merge_verification_20260528.md` as the current release-state reference.
- Preserve and use the expanded known-case benchmark before any future runtime/model/scoring-adjacent work. The current corpus covers 30 compact cases with false-positive, sidecar-context, and public-source metadata controls.
- If more validation work is desired, use the public-case human labeling packet and `public_case_label_intake_v1` schema for exact-wallet candidates. The current evidence bridge found no safe exact-wallet upgrades and no named-user local wallet candidates.
- Use the known-case benchmark maintenance checklist before adding or changing cases. Exact-wallet upgrades require accepted intake plus a separate fixture update campaign; maintenance work alone must not alter model/runtime behavior.
- Decide push/PR grouping only when the owner explicitly wants to publish; Release Candidate V3 verification passed at `2dd851f` before the V3 report commit.
- Use `AI_CONTROL/STRATEGIC_OPERATING_SYSTEM.md` for every open-ended strategic campaign and score candidate paths before implementation.
- Create a ChatGPT strategic review from `AI_CONTROL/STRATEGIC_REVIEW_PACKET.md` if external review is desired before the next product campaign.
- Run bounded Event Forensic performance/pagination work only from measured bottlenecks and explicit target selection.

## Should Do
- If the owner asks for cleanup, run a separate branch-cleanup campaign: confirm `main` is still verified, then delete the remote/local publication branch only if explicitly approved.
- Add exact-wallet public-case benchmark rows only after a future intake label passes validation and is accepted for benchmark use. Current public cases are named-user, market-level, or pattern-level controls only, with compact local refs that explicitly do not prove wallet identity.
- Add more tests around archive visibility, browser report normalization, event eligibility, and partial/live Event Forensic modes.
- Create a provider/query micro-probe packet for one selected truncated market before any production pagination expansion.
- For bounded indexer follow-up, preserve the target registry, scoped compare tooling, per-target public-trade collection metadata, warehouse RFC packet, W0 contract helper/readiness audit fields, W1 manual local review command, W2 registry/retention manifest, W3 analyst query command, and W4 pointer implementation. Next highest-leverage work is owner-approved push/PR; W4 visible UI, scheduler/background mode, warehouse write/copy behavior, broader live ingestion, copied metrics, and production scoring/gate use remain separate approval gates.
- Improve analyst-facing strategic summaries and review packet freshness checks.
- Validate the weak-history near-certainty demotion on fresh live single-market and whole-event outputs when the operator wants confirmation.
- Decide whether root `AGENTS.md` should remain local-only or become tracked repository policy in a separate process-control campaign.
- If desired, run a future Tk UI retirement RFC. Current decision freezes `app/desktop.py` as historical/reference-only; do not treat it as release UI or update it as a supported fallback without approval.

## Later
- Consider report-embedded replay metadata only after a top-slice vs all-candidate size-budget RFC.
- Consider storage-backed replay only after a storage schema/retention RFC.
- Consider replacing runtime Babel only after a build-pipeline/precompile RFC and UI equivalence proof.
- Consider pUSD/on-chain collateral tracing only after canonical token/onramp/exchange addresses, source quality, production-truth policy, and tracing semantics are decided.

## RFC-Only / Approval-Gated
- Phase 3 capital-at-risk runtime implementation.
- Production pagination expansion.
- Wallet API boundary batching if it changes request contracts or completeness assumptions.
- New scoring weights, severity labels, or gates.
- Sidecar-to-runtime integrations.
- New external dependencies or live service behavior.
