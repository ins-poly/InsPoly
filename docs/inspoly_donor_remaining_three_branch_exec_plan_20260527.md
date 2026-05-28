# InsPoly Donor Remaining Three-Branch ExecPlan

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This plan is adapted for InsPoly from the OpenAI Cookbook guidance on long-running Codex execution plans: a useful plan must be self-contained, novice-guiding, outcome-focused, explicit about validation, and maintained as a living document while work proceeds. The reference article is `https://developers.openai.com/cookbook/articles/codex_exec_plans`.

Date: 2026-05-27 EEST

Status: executed locally as a sidecar/RFC strategic campaign; no runtime integration

Current executor: Codex using `strategic-autonomy-review`

## Purpose / Big Picture

The donor-repository reform program has already delivered the safe local foundation: protocol semantics, ledger helpers, optional indexer sidecars, shadow metrics, benchmark controls, Event Forensic performance work, browser offline readiness, replay sidecars, and release-candidate packaging. Three donor-derived strategic branches remain valuable but are approval-gated:

1. Optional live indexer / warehouse mode.
2. Sidecar context to analyst report and UI integration.
3. pUSD / CLOB collateral semantics plus Phase 3 capital evidence.

This ExecPlan turns those three branches into a long, safe, multi-stage campaign. The goal is not to force production integration. The goal is to let Codex work for a long run, gather evidence, build sidecar/RFC scaffolding, and stop only at real approval gates. After successful execution, the repository should have clear decisions and implementation-ready plans for the remaining donor-derived opportunities, while preserving current forensic behavior.

The visible outcome is a set of current-state docs, compact JSON summaries, optional sidecar-only tools/tests, and explicit gate decisions for all three branches. A human should be able to inspect the outputs and know exactly whether the next step is safe local work, product approval, operator approval, or no action.

## Progress

- [x] (2026-05-27 EEST) Initial ExecPlan authored from the donor handoff, current RC V3 state, and the remaining three strategic branches.
- [x] (2026-05-27 EEST) Executor produced a Strategic Campaign Brief before editing.
- [x] (2026-05-27 EEST) Milestone 0 state recovery and source-of-truth reconciliation completed.
- [x] (2026-05-27 EEST) Branch A live indexer / warehouse evidence campaign completed.
- [x] (2026-05-27 EEST) Branch B sidecar context report/UI readiness campaign completed.
- [x] (2026-05-27 EEST) Branch C pUSD / CLOB collateral and Phase 3 evidence campaign completed.
- [x] (2026-05-27 EEST) Cross-branch integration decision and roadmap completed.
- [x] (2026-05-27 EEST) Final validation, AI_CONTROL updates, PROJECT_MEMORY update, and local commit completed if appropriate.

## Surprises & Discoveries

Record unexpected findings here as the plan is executed. Examples include provider behavior that invalidates an indexer assumption, local artifacts that make a report-only context safer than expected, or pUSD collateral evidence that contradicts existing USDC-only assumptions.

- Observation: initial plan created with all three branches approval-gated by default.
  Evidence: current release state records Phase 3 runtime, production pagination expansion, replay persistence, and sidecar-to-runtime integration as blocked without separate approval.

- Observation: Branch A had no existing read-only inspector for an already-created indexer SQLite sidecar DB.
  Evidence: existing `tools/indexer_fixture_dry_run.py` writes fixture rows and summarizes counts, but does not audit an arbitrary existing DB for missing schema, stale cursors, malformed raw JSON, or duplicate indicators.

- Observation: Branch B preview-index work would duplicate existing sidecar tools.
  Evidence: `tools/shadow_artifact_corpus_inventory.py`, `tools/render_shadow_context_preview.py`, `tools/generate_shadow_review_packets.py`, and `tools/shadow_sidecar_value_dashboard.py` already cover artifact inventory, preview rendering, review packet indexes, and sidecar value decisions.

- Observation: Branch C can advance only through static, unknown-safe semantics and source research.
  Evidence: current funding traces remain USDC/USDC.e-only, Phase 3 has `0` safe real sensitive SELL rows, and no verified pUSD/CLOB collateral source facts exist in repo state.

## Decision Log

- Decision: Treat this as a strategic multi-branch evidence and planning campaign, not a production integration campaign.
  Rationale: the donor handoff explicitly says indexer, shadow metrics, report/UI integration, live indexing, and collateral/funding semantics require separate approval before runtime adoption.
  Date/Author: 2026-05-27 EEST / Codex.

- Decision: Branch order is A, then B, then C, then cross-branch decision.
  Rationale: indexer/warehouse evidence can feed sidecar context readiness; sidecar/report readiness clarifies what context is useful before touching Phase 3/collateral evidence; Phase 3 remains the highest-risk runtime area and should come after evidence-only work.
  Date/Author: 2026-05-27 EEST / Codex.

- Decision: Every branch must be independently stoppable.
  Rationale: the work spans live/network indexing, analyst UX/report integration, and capital semantics. Any one branch may hit a gate without blocking the others.
  Date/Author: 2026-05-27 EEST / Codex.

- Decision: Implement A3 as a read-only DB readiness audit.
  Rationale: it is non-duplicative, local-only, no-network, and directly improves future operator review without enabling live indexing.
  Date/Author: 2026-05-27 EEST / Codex.

- Decision: Do not implement B3 preview index.
  Rationale: existing sidecar inventory, preview, packet, and dashboard tools already cover the safe index/preview need; another index would add maintenance without reducing integration risk.
  Date/Author: 2026-05-27 EEST / Codex.

- Decision: Implement C3 only as static unknown-safe semantics.
  Rationale: fixture/static semantics can encode source-quality rules and preserve unknowns without claiming real pUSD/collateral addresses or integrating funding runtime.
  Date/Author: 2026-05-27 EEST / Codex.

- Decision: Final combined gate is `three_branch_execplan_no_safe_runtime_changes`.
  Rationale: all branches produced useful sidecar/RFC evidence, but every production/live/UI/funding/Phase 3 boundary remains approval-gated.
  Date/Author: 2026-05-27 EEST / Codex.

## Outcomes & Retrospective

- Milestone 0 completed with `docs/inspoly_donor_remaining_three_branch_scorecard_20260527.md` and `validation_outputs/inspoly_donor_remaining_three_branch_scorecard_20260527.json`. It recorded head `df043e24a4ad5e349e450d893db95b195732da23`, branch `main`, 50 commits ahead of `origin/main`, protected local-only buckets, and the no-push/no-production-integration gate.
- Branch A completed with `docs/inspoly_indexer_sidecar_current_capability_audit_20260527.md`, `docs/inspoly_indexer_live_operator_plan_rfc_20260527.md`, compact JSON summaries, and the read-only `tools/indexer_sidecar_readiness_audit.py` plus tests. Live indexing remains blocked pending operator approval.
- Branch B completed with `docs/inspoly_sidecar_context_current_inventory_20260527.md`, `docs/inspoly_sidecar_context_analyst_integration_rfc_20260527.md`, and compact JSON summaries. Report-copying and UI panels remain blocked; B3 was intentionally skipped as duplicative.
- Branch C completed with `docs/inspoly_pusd_clob_collateral_semantics_gap_audit_20260527.md`, `docs/inspoly_pusd_clob_collateral_research_rfc_20260527.md`, compact JSON summaries, and static unknown-safe collateral semantics tests. Phase 3 and funding runtime remain blocked.
- Cross-branch decision completed with `docs/inspoly_donor_remaining_three_branch_decision_20260527.md` and `validation_outputs/inspoly_donor_remaining_three_branch_decision_20260527.json`. No push/PR was performed.
- Validation completed: all new compact JSON parsed, new sidecar code compiled, focused indexer/alert tests passed 44 tests, focused collateral/protocol/ledger/Phase 3 tests passed 55 tests, `git diff --check` passed, and direct runtime import scans found no `indexer_sidecar_readiness_audit` or `polymarket_collateral_semantics` imports in production paths.

## Context and Orientation

InsPoly is a local-first forensic toolkit for Polymarket. Its production value is defensible case analysis, not automated trading or realtime execution. The core production flows are:

- `app/scanner.py`: Recent Scanner.
- `app/archive_scanner.py`: Archive Researcher.
- `app/event_forensic.py`: Event Forensic Analyzer.
- `app/funding_context.py`: funding trace context.
- `app/polymarket.py`: public Polymarket API access and normalization.
- `app/browser_desktop.py`, `app/browser_ui.html`, `app/browser_event_forensic_ui.html`: active browser-backed UI paths.

The current release candidate has already implemented or documented these major outcomes:

- Side/Outcome Phase 2/4 semantics are stable.
- Event Forensic weak-history demotion is implemented.
- Event Forensic scope semantics are explicit.
- Event Forensic performance/pagination/provider semantics are measured and mostly blocked from further runtime expansion without evidence.
- Phase 3 capital-at-risk runtime is blocked until new source fields / stronger sensitive SELL evidence.
- Browser strict offline boot is ready.
- Replay persistence remains sidecar-only.
- Public exact-wallet benchmark labels remain zero; human label intake is required.
- Legacy Tk UI is frozen as reference-only.
- Push/PR is user-gated.

Important current documents:

- `docs/inspoly_reform_handoff_external_repos_20260521.md`
- `docs/inspoly_reform_integration_readiness_report_20260521.md`
- `docs/inspoly_reform_post9e_sidecar_campaign_report_20260521.md`
- `docs/inspoly_release_candidate_v3_state_20260527.md`
- `docs/inspoly_future_pr_draft_20260527.md`
- `docs/inspoly_push_approval_checklist_v3_20260527.md`
- `docs/inspoly_local_release_master_index_20260525.md`
- `AI_CONTROL/STRATEGIC_OPERATING_SYSTEM.md`
- `AI_CONTROL/CURRENT_STATE.md`
- `AI_CONTROL/INVARIANTS_AND_GUARDRAILS.md`
- `AI_CONTROL/DECISION_LOG.md`
- `AI_CONTROL/STRATEGIC_BACKLOG.md`

Definitions used in this plan:

- Sidecar: code or data that can run manually and locally without being imported by production scanner/archive/Event Forensic paths.
- Runtime integration: production code path imports or uses the feature during normal scanner/archive/Event Forensic/UI execution.
- Report-copying: copying sidecar-derived fields into production report JSON/CSV/MD outputs.
- Warehouse: a durable cache/indexer layer that stores market, trade, wallet, orderbook, or user state for reuse.
- Live indexing: network-backed ingestion that fetches fresh data from Polymarket or on-chain providers.
- pUSD / CLOB collateral semantics: the source-of-funds and capital-at-risk interpretation for CLOB V2 collateral flows beyond current USDC-centric funding logic.
- Approval gate: a boundary where Codex may produce RFCs, tests, probes, or sidecar tools, but must not implement production behavior without explicit operator approval.

## Non-Negotiable Invariants

The executor must preserve these invariants throughout the plan:

- Do not push or create a PR.
- Do not change scoring weights, thresholds, severity labels, Strong Risk, HER routing, funding eligibility, candidate admission, or sorting.
- Do not implement Phase 3 capital runtime.
- Do not mutate saved artifacts.
- Do not add private keys, CLOB auth, order placement, trading execution, or bot logic.
- Do not make Postgres, Redis, Graph Node, a live indexer, or a network service required for existing local workflows.
- Do not import sidecar helpers into production scanner/archive/Event Forensic/browser paths unless the current branch explicitly reaches an approved runtime implementation gate. This plan does not grant that approval.
- Keep missing funding and unavailable collateral context as `unknown`, not `none`.
- Keep old report compatibility absent-safe.
- Do not stage `PROJECT_MEMORY.md`.
- Do not delete local-only review packets, raw outputs, or old manifests.

## Strategic Campaign Brief Requirement

Before editing, the executor must write a Strategic Campaign Brief in the conversation. The brief must cover:

1. Current state.
2. Product objective.
3. Candidate paths and tradeoffs.
4. Recommended path.
5. Why this path is highest leverage now.
6. Files/modules likely affected.
7. Protected invariants and approval gates.
8. Validation plan.
9. Stop conditions.
10. Expected state updates.

If the brief discovers that the user has not approved a required boundary, continue only with RFC/probe/report work and do not implement that boundary.

## Plan of Work

The plan has one preparation milestone, three branch milestones, one cross-branch decision milestone, and one final validation/recording milestone.

Milestone 0 recovers the current state and creates the initial branch scorecard. Branch A investigates whether optional live indexer / warehouse work can safely advance beyond the existing sidecar skeleton. Branch B evaluates whether sidecar context can be surfaced to analysts without changing scoring or creating confusion. Branch C evaluates pUSD / CLOB collateral and Phase 3 capital evidence without implementing runtime capital behavior. The cross-branch milestone decides whether any branch is ready for a future product/operator approval request, and the final milestone validates and records the result.

## Milestone 0 - State Recovery and Branch Scorecard

Start by rebuilding current context from code, memory, AI_CONTROL, and docs. The purpose is to prevent redoing solved work or crossing approval gates by accident.

Read these files first:

- `AGENTS.md`
- `PROJECT_MEMORY.md`
- all AI_CONTROL files listed in Context and Orientation
- `docs/inspoly_reform_handoff_external_repos_20260521.md`
- `docs/inspoly_reform_integration_readiness_report_20260521.md`
- `docs/inspoly_reform_post9e_sidecar_campaign_report_20260521.md`
- `docs/inspoly_release_candidate_v3_state_20260527.md`
- `docs/inspoly_local_release_master_index_20260525.md`

Inspect current git state:

    cd <repo>
    git status --short
    git rev-parse --abbrev-ref HEAD
    git rev-list --count origin/main..HEAD

Create a current scorecard for the three branches. For each branch, score product leverage, risk reduction, evidence readiness, reversibility, dependency unblocking, approval load, and tunnel-vision risk. The scorecard should decide whether to run all branches in this execution or stop after a branch. The default is to run all three unless a branch uncovers an approval gate that invalidates safe sidecar/RFC work.

Output files for Milestone 0:

- `docs/inspoly_donor_remaining_three_branch_scorecard_20260527.md`
- `validation_outputs/inspoly_donor_remaining_three_branch_scorecard_20260527.json`

Acceptance for Milestone 0:

- The scorecard names the latest commit, branch ahead count, and current gates.
- It explicitly says this plan does not authorize push/PR or production integration.
- It lists all local-only buckets that remain unstaged.

## Branch A - Optional Live Indexer / Warehouse Mode

Branch A exists because `jagnani73/insidepoly`, `ZkAGI/polymarket-insider`, and related donor systems show value in durable ingestion, cursors, health checks, score history, and aggregate views. InsPoly already has local indexer sidecar models/storage/adapters/fixture replay. What remains is deciding whether live indexing or warehouse mode is justified and how it would stay optional.

### A1 - Existing Indexer Sidecar Audit

Audit these files and tests:

- `app/indexer/`
- `tools/indexer_fixture_dry_run.py`
- `tests/test_indexer_storage.py`
- `tests/test_indexer_adapters.py`
- `tests/test_indexer_fixture_dry_run.py`
- `app/indexer/alerts.py`
- `tests/test_alerts_sidecar.py`
- `docs/inspoly_sidecar_checkpoint_completion_20260525.md`

Answer:

- What indexer data can already be stored locally?
- What idempotency and health guarantees already exist?
- What is missing for live ingestion?
- What would make production scanner/archive/Event Forensic depend on it, and why is that currently forbidden?

Produce:

- `docs/inspoly_indexer_sidecar_current_capability_audit_20260527.md`
- compact JSON under `validation_outputs/`

### A2 - Live Indexer Operator Plan RFC

Create an RFC-only plan for bounded live indexing. Do not implement live indexing. The RFC must specify:

- allowed data types: markets, trades, orderbook snapshots, cursors, optional health rows;
- disallowed data types: private user socket data, auth, orders, private keys, trading;
- hard runtime boundaries: no automatic startup, no production imports, no background worker unless separately approved;
- operator inputs: target market/event list, max markets, max pages, max rows, timeout, output DB path;
- safety: idempotent replay, cursor health, dry-run mode, no saved artifact mutation;
- local storage: SQLite sidecar first; Postgres/Redis only as future optional RFC;
- rollback plan.

Produce:

- `docs/inspoly_indexer_live_operator_plan_rfc_20260527.md`
- `validation_outputs/inspoly_indexer_live_operator_plan_rfc_20260527.json`

Gate decisions for Branch A:

- `indexer_live_operator_plan_ready_no_runtime`
- `indexer_live_blocked_needs_operator_approval`
- `indexer_warehouse_optional_rfc_needed`
- `indexer_no_safe_next_step`

### A3 - Optional Sidecar Health and Warehouse Readiness Tool

If safe and useful, add a read-only local tool that inspects an existing sidecar DB and reports readiness for future live indexing. It must not fetch network data.

Possible file:

- `tools/indexer_sidecar_readiness_audit.py`
- `tests/test_indexer_sidecar_readiness_audit.py`

The tool should report:

- schema presence;
- cursor count and cursor health;
- market/trade/orderbook row counts;
- duplicate/idempotency indicators;
- malformed raw JSON count;
- recommended next action.

Do not add live fetchers. If this tool is not useful because equivalent tooling exists, document that and do not duplicate.

## Branch B - Sidecar Context to Analyst Report/UI Integration

Branch B exists because donor systems showed value in score history, watchlists, alerts, trader profiles, PnL, and microstructure context. InsPoly has built sidecar helpers and repeatedly decided not to copy them into production reports because useful metric density was low and confusion risk was high. The remaining strategic question is whether any narrow analyst-facing integration is now safe, or whether the final answer remains sidecar-only.

### B1 - Current Sidecar Context Inventory

Audit:

- `app/shadow_metrics.py`
- `app/trader_profile_context.py`
- `app/microstructure_context.py`
- `app/polymarket_ledger.py`
- `app/event_forensic_replay.py`
- `app/indexer/alerts.py`
- `tools/render_shadow_context_preview.py`
- `tools/shadow_sidecar_value_dashboard.py`
- `tools/generate_shadow_review_packets.py`
- `docs/inspoly_reform_post9e_sidecar_campaign_report_20260521.md`
- `docs/inspoly_analyst_delivery_readiness_20260526.md`
- `docs/inspoly_event_forensic_replay_persistence_product_decision_20260526.md`

Produce a current sidecar inventory:

- available context families;
- evidence quality;
- unknown/not-computed rates where known;
- duplicate/confusion risk;
- whether the context is analyst-useful;
- whether it is safe for report-copying, browser display, tool-only preview, or blocked.

Output:

- `docs/inspoly_sidecar_context_current_inventory_20260527.md`
- compact JSON under `validation_outputs/`

### B2 - Analyst Integration Options RFC

Evaluate only these safe options:

1. Keep all context sidecar-only.
2. Add a manual browser-openable sidecar preview index, not production report fields.
3. Add optional top-level report metadata that only points to sidecar artifacts, not copies metrics.
4. Add a tiny analyst-only UI panel that reads explicit sidecar files selected by the operator.

Do not implement report-copying or UI panels unless evidence and approval are explicit. This plan does not grant approval.

The RFC must include:

- why prior report-copying was blocked;
- exact data that would be shown;
- absent-safe old report behavior;
- no scoring/routing effect;
- how analysts would distinguish advisory context from verdicts;
- rollback plan.

Output:

- `docs/inspoly_sidecar_context_analyst_integration_rfc_20260527.md`
- `validation_outputs/inspoly_sidecar_context_analyst_integration_rfc_20260527.json`

Gate decisions for Branch B:

- `sidecar_context_keep_sidecar_only_final`
- `sidecar_context_preview_index_ready`
- `sidecar_context_report_pointer_rfc_ready`
- `sidecar_context_ui_panel_needs_product_approval`
- `sidecar_context_no_safe_integration`

### B3 - Optional Preview Index

If evidence supports it and it remains purely sidecar-only, add a small read-only preview index generator that inventories existing sidecar preview/review packet outputs and writes a compact index.

Possible files:

- `tools/sidecar_context_preview_index.py`
- `tests/test_sidecar_context_preview_index.py`

The tool must not import scanner/archive/Event Forensic runtime paths. It must not write reports. It must not change UI. It should output only to a caller-supplied path or `validation_outputs/`.

If existing tools already cover this, do not duplicate. Instead, update docs with the existing command.

## Branch C - pUSD / CLOB Collateral Semantics and Phase 3 Evidence

Branch C exists because donor protocol/ledger work highlighted that current funding/capital analysis remains USDC-centric, while CLOB V2 collateral and pUSD/on-chain flows may affect future funding attribution and capital-at-risk interpretation. Phase 3 runtime is blocked because current evidence cannot safely compute SELL max-loss for sensitive contexts.

### C1 - Current Funding and Capital Semantics Audit

Audit:

- `app/funding_context.py`
- `app/polymarket_protocol.py`
- `app/polymarket_ledger.py`
- `docs/inspoly_phase3_capital_final_evidence_review_20260526.md`
- `docs/inspoly_phase3_capital_blocker_register_20260526.md`
- `docs/inspoly_phase3_capital_at_risk_formula_contract_20260525.md`
- `tests/test_phase3_capital_unblock.py`
- `tests/test_phase3_real_sell_evidence_expansion.py`
- `tests/test_polymarket_protocol_semantics.py`
- `tests/test_polymarket_ledger.py`

Answer:

- Where does current funding logic assume USDC/USDC.e?
- Where does current ledger logic preserve cash vs size*price ambiguity?
- What exact source fields would unblock Phase 3?
- What pUSD/on-chain collateral facts are currently unknown?
- What must remain `unknown` rather than inferred?

Output:

- `docs/inspoly_pusd_clob_collateral_semantics_gap_audit_20260527.md`
- compact JSON under `validation_outputs/`

### C2 - pUSD / Collateral Source Research Plan

Create an RFC-only research plan. Do not implement runtime tracing.

The plan must define:

- which canonical token addresses / contract addresses are needed;
- which source types are acceptable: official docs, verified contracts, local chain artifacts, trusted explorer pages;
- which source types are not acceptable: blogs without addresses, timing inference, heuristic wallet clustering;
- how to encode pUSD/collateral source facts in fixtures;
- how to keep missing facts `unknown`;
- how to test without live RPC by using static fixtures;
- what would be required before any funding runtime integration.

Output:

- `docs/inspoly_pusd_clob_collateral_research_rfc_20260527.md`
- `validation_outputs/inspoly_pusd_clob_collateral_research_rfc_20260527.json`

Gate decisions for Branch C:

- `pusd_collateral_research_rfc_ready`
- `pusd_collateral_needs_verified_addresses`
- `phase3_runtime_still_blocked`
- `phase3_source_fields_needed`

### C3 - Optional Static Fixture Semantics

If safe, add static tests/fixtures for the semantics we already know from current helpers, without claiming real pUSD contract truth.

Possible files:

- `tests/fixtures/pusd_collateral_semantics/`
- `tests/test_pusd_collateral_semantics.py`
- `app/polymarket_collateral_semantics.py`

Only do this if it remains pure, static, and explicitly unknown-safe. Do not hardcode unverified real addresses. Do not integrate into funding runtime.

Acceptance:

- tests prove unknown-safe behavior;
- missing contract/address facts remain `unknown`;
- no production funding behavior changes.

## Cross-Branch Decision Milestone

After Branches A, B, and C, produce one integrated decision report:

- `docs/inspoly_donor_remaining_three_branch_decision_20260527.md`
- `validation_outputs/inspoly_donor_remaining_three_branch_decision_20260527.json`

The report must include:

- branch outcomes;
- branch gates;
- which branch is ready for approval;
- which branch remains blocked;
- which branch produced sidecar-only value;
- exact future operator/product decisions needed;
- recommended next 3-campaign roadmap;
- explicit statement that no push/PR was performed.

Possible final combined gates:

- `three_branch_execplan_completed_all_sidecar_rfc`
- `three_branch_execplan_indexer_approval_ready`
- `three_branch_execplan_sidecar_ui_approval_ready`
- `three_branch_execplan_pusd_research_ready`
- `three_branch_execplan_blocked_by_approval_gates`
- `three_branch_execplan_no_safe_runtime_changes`

## Concrete Steps

Run commands from `<repo>`.

Initial status:

    git status --short
    git rev-parse --abbrev-ref HEAD
    git rev-list --count origin/main..HEAD

Search examples:

    rg -n "sidecar|shadow|microstructure|trader_profile|score_history|watchlist|alert" app tools tests docs AI_CONTROL
    rg -n "Phase 3|capital|pUSD|USDC|collateral|funding" app tools tests docs AI_CONTROL
    rg -n "indexer|cursor|orderbook|health|warehouse" app tools tests docs AI_CONTROL

Validation commands depend on touched files. Use the smallest sufficient set first, then broaden if runtime or shared tooling changed.

For docs/JSON-only changes:

    python3 -m json.tool validation_outputs/<new-file>.json > /tmp/<new-file>.json.validated
    git diff --check

For new/changed Python tools/tests:

    python3 -m py_compile <changed files>
    python3 -m unittest <changed test modules>

For Branch A if indexer tools/tests change:

    python3 -m unittest tests.test_indexer_storage tests.test_indexer_adapters tests.test_indexer_fixture_dry_run tests.test_alerts_sidecar

For Branch B if sidecar context tools/tests change:

    python3 -m unittest tests.test_shadow_metrics tests.test_shadow_context_preview tests.test_microstructure_context tests.test_trader_profile_context tests.test_shadow_integration_gate_readiness

For Branch C if funding/ledger/protocol tests change:

    python3 -m unittest tests.test_polymarket_protocol_semantics tests.test_polymarket_ledger tests.test_phase3_capital_unblock tests.test_phase3_real_sell_evidence_expansion

If any production runtime code changes, run full suite:

    python3 -m unittest discover -s tests -p 'test_*.py'

Before committing:

    git diff --check
    git diff --cached --check
    git diff --cached --name-only

Do not commit unless the user requested or the executor's campaign policy allows local commits. Never push.

## Validation and Acceptance

The plan is successful if:

- all three branches have current evidence reports and gate decisions;
- any code added is sidecar-only or pure helper/test code;
- no production scoring/gate/storage/UI sorting behavior changes;
- no Phase 3 runtime implementation;
- no live indexer or network service starts automatically;
- all new JSON files parse;
- relevant focused tests pass;
- `git diff --check` passes;
- `PROJECT_MEMORY.md` is updated local-only;
- AI_CONTROL state/backlog/decision files are updated if gates change;
- final report recommends the next three campaigns or approval decisions.

If a branch produces only a blocked decision, that can still be a successful outcome if the blocker is explicit and evidence-based.

## Idempotence and Recovery

All tools created by this plan must be idempotent. Re-running them should either produce the same compact output or update a timestamped output without mutating production reports.

If a tool partially writes output, it should write to a caller-supplied directory or `validation_outputs/` only. Do not write into saved report directories.

Rollback for docs/JSON-only work is deleting the new docs and compact JSON files plus reverting AI_CONTROL updates. Rollback for sidecar tool work is deleting the new sidecar tool/tests/fixtures. No production database migration should exist.

If a planned runtime change seems necessary, stop and convert it to an RFC. This ExecPlan does not grant runtime integration approval.

## Artifacts and Notes

Use compact committed JSON summaries for evidence. Keep bulky raw outputs local-only.

Do not stage:

- `PROJECT_MEMORY.md`
- `release_manifests/`
- `shadow_review_packets/`
- `side_outcome_review_packets/`
- raw live output directories
- bulky generated evidence

Update `PROJECT_MEMORY.md` after completion, but keep it unstaged unless the owner explicitly changes that policy.

## Interfaces and Dependencies

Branch A should use existing `app.indexer` modules and avoid new service dependencies. SQLite sidecar storage is acceptable; Postgres/Redis/Graph Node are not required dependencies.

Branch B should use existing sidecar modules and tools. It must not import them into scanner/archive/Event Forensic production paths unless a future approval campaign allows it.

Branch C should use existing protocol, ledger, and funding modules. It must not hardcode unverified pUSD/collateral addresses as production truth.

No branch should add external dependencies without an explicit RFC and approval.
