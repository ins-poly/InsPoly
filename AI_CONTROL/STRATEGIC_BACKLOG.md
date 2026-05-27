# Strategic Backlog

Last updated: 2026-05-27 EEST.

## Must Preserve
- Do not change scoring/gates/visibility semantics without explicit approval.
- Do not stage/push local-only memory, generated evidence, or review packets without explicit approval.
- Keep sidecar helpers out of production runtime paths.
- Keep funding `unknown` distinct from `none`.
- Keep selected-market vs whole-event semantics explicit.
- Keep Strategic Operating System autonomy bounded by approval gates.

## Highest-Leverage Next Work
- Preserve and use the expanded known-case benchmark before any future runtime/model/scoring-adjacent work. The current corpus covers 30 compact cases with false-positive, sidecar-context, and public-source metadata controls.
- If more validation work is desired, use the public-case human labeling packet and `public_case_label_intake_v1` schema for exact-wallet candidates. The current evidence bridge found no safe exact-wallet upgrades and no named-user local wallet candidates.
- Use the known-case benchmark maintenance checklist before adding or changing cases. Exact-wallet upgrades require accepted intake plus a separate fixture update campaign; maintenance work alone must not alter model/runtime behavior.
- Decide push/PR grouping only when the owner explicitly wants to publish; release-candidate verification already passed at `ad27400`.
- Use `AI_CONTROL/STRATEGIC_OPERATING_SYSTEM.md` for every open-ended strategic campaign and score candidate paths before implementation.
- Create a ChatGPT strategic review from `AI_CONTROL/STRATEGIC_REVIEW_PACKET.md` if external review is desired before the next product campaign.
- Run bounded Event Forensic performance/pagination work only from measured bottlenecks and explicit target selection.

## Should Do
- Add exact-wallet public-case benchmark rows only after a future intake label passes validation and is accepted for benchmark use. Current public cases are named-user, market-level, or pattern-level controls only, with compact local refs that explicitly do not prove wallet identity.
- Add more tests around archive visibility, browser report normalization, event eligibility, and partial/live Event Forensic modes.
- Create a provider/query micro-probe packet for one selected truncated market before any production pagination expansion.
- Improve analyst-facing strategic summaries and review packet freshness checks.
- Validate the weak-history near-certainty demotion on fresh live single-market and whole-event outputs when the operator wants confirmation.
- Decide whether root `AGENTS.md` should remain local-only or become tracked repository policy in a separate process-control campaign.
- If desired, run a future Tk UI retirement RFC. Current decision freezes `app/desktop.py` as historical/reference-only; do not treat it as release UI or update it as a supported fallback without approval.

## Later
- Consider report-embedded replay metadata only after a top-slice vs all-candidate size-budget RFC.
- Consider storage-backed replay only after a storage schema/retention RFC.
- Consider replacing runtime Babel only after a build-pipeline/precompile RFC and UI equivalence proof.
- Consider pUSD/on-chain collateral tracing only after canonical token/onramp/exchange addresses and tracing semantics are decided.

## RFC-Only / Approval-Gated
- Phase 3 capital-at-risk runtime implementation.
- Production pagination expansion.
- Wallet API boundary batching if it changes request contracts or completeness assumptions.
- New scoring weights, severity labels, or gates.
- Sidecar-to-runtime integrations.
- New external dependencies or live service behavior.
