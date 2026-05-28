# AI_CONTROL Project Memory

Last updated: 2026-05-26 EEST.

This is the compact strategic memory for external review loops. The full operational memory remains `../PROJECT_MEMORY.md`; when the two conflict, use the root memory and current code as higher authority.

## Project Purpose
- InsPoly is a local-first Polymarket suspicious-trade investigation toolkit.
- It produces analyst leads, evidence bundles, and diagnostics; it is not a legal accusation system, investment system, hosted service, or automated trading tool.
- The three main user-facing flows are Recent Scanner, Archive Researcher, and Event Forensic Analyzer.
- The core model is explainable heuristic scoring, not ML.
- Outputs are local JSON/CSV/Markdown/SQLite artifacts and are part of the analyst workflow, not disposable temp files.

## Architecture Summary
- Entry point: `python3 -m app ...`, routed by `app/cli.py`.
- Core scoring: `app/scanner.py`; reused by archive and event forensic modes.
- Archive mode: `app/archive_scanner.py`, historical-window exports and visibility tiers.
- Event forensic mode: `app/event_forensic.py`, event/market resolution, candidate replay, wallet/cluster rankings, and report bundles.
- Browser servers: `app/browser_desktop.py` and `app/event_forensic_desktop.py`.
- Browser frontends: `app/browser_ui.html` and `app/browser_event_forensic_ui.html`.
- External data: Polymarket Gamma/Data/CLOB/public pages; optional Polygon RPC for funding traces.
- Local persistence: `.inspoly*/` SQLite/report roots plus top-level output directories.
- Sidecar helpers exist for benchmark schemas, protocol/ledger context, local indexing, shadow/profile/microstructure context, replay, and audits; they are not production runtime paths unless explicitly approved.

## Key Decisions To Preserve
- The project is rule-based and explainable; LLMs may review packets but must not become production scoring logic without a separate tested design.
- Scanner/archive/event forensic share base scoring contracts; changes in `app/scanner.py` ripple across modes.
- Funding `unknown` is not equivalent to clean/no funding; failed or unavailable lookups must remain unknown.
- Legacy report normalization and upstream API fallbacks are intentional compatibility logic.
- Event Forensic selected-market scope must not silently become whole-event scope.
- Phase 3 capital-at-risk runtime normalization remains blocked; only sidecar/source-quality evidence work is allowed unless approved separately.
- Replay persistence is sidecar-only in the current product state.
- Browser boot assets are vendored locally; runtime Babel remains accepted for now and replacing it requires a separate build/equivalence campaign.
- Strategic autonomy is process-only: `AI_CONTROL/STRATEGIC_OPERATING_SYSTEM.md` governs campaign selection, but it does not grant permission to cross approval-gated product boundaries.

## Current Gate State
- Side/Outcome Phase 2/4: stable after benchmark and drift audits.
- Event Forensic weak-history near-certainty review-bucket demotion: implemented and validated locally; live distribution follow-up remains useful.
- Event Forensic scope semantics: selected-market vs whole-event semantics implemented; preserve exact scope copy and behavior.
- Event Forensic performance: scorer-context optimizations landed; further runtime speed work should target measured wallet-context loading or event-wide trade collection, not scoring semantics.
- Pagination/provider strategy: monitor/RFC state only; no production pagination expansion.
- Phase 3 capital-at-risk: sidecar-only final for now; runtime remains blocked.
- Replay persistence: sidecar-only final for now.
- Browser strict offline: implementation committed; both browser UIs boot from vendored React/ReactDOM/Babel assets.
- Known-case benchmark: expanded to `known_case_benchmark_v3` with 30 compact offline cases, including false-positive, sidecar-context, and public-source metadata controls. Public cases remain named-user, market-level, or pattern-level only; exact-wallet public cases are still blocked until source/local-artifact proof exists.
- Strategic Operating System: implemented as the required ORIENT -> SELECT -> PLAN -> EXECUTE -> VALIDATE -> RECORD loop for non-trivial work.
- Push/PR/release: user-gated.

## Fragile Areas
- `app/scanner.py` scoring weights, thresholds, severity gates, suppressors, and raw metrics.
- Event Forensic report shape, `display_*` top-slice payloads, full CSV/raw exports, and selected-market vs whole-event semantics.
- Archive visibility tiers and old naming such as `excluded_hidden`.
- Browser report normalization for legacy saved reports.
- Funding trace quality and cache semantics, especially `unknown` vs `none`.
- Polymarket API fallbacks: Gamma 422, trade pagination limits, slug 403, and public-page `__NEXT_DATA__`.
- Sidecar helpers that may look useful but must not be imported into production runtime paths without an approval gate.

## Latest Strategic Snapshot
- Latest release-candidate commit verified: `ad27400 Verify local release candidate state`.
- Latest pre-push dry-run commit inspected: `05d688d Add final pre-push packaging dry run`.
- Latest runtime-affecting commit inspected: `0ce05da Add local browser offline runtime assets`.
- Root `PROJECT_MEMORY.md` is intentionally ignored/local-only and should not be staged by default.
- Current local release-candidate gate: `local_release_candidate_verified`.
- Current untracked local artifacts include release manifests and review packets under `release_manifests/`, `shadow_review_packets/`, and `side_outcome_review_packets/`.
- Pre-existing process-control files were consolidated for repo review: `AI_CONTROL/*.md`, `.gitignore` visibility rules, and `skills/strategic-autonomy-review/SKILL.md`.
- Root `AGENTS.md` remains ignored/local-only pending a separate user decision; the committed `AI_CONTROL/` layer and repo-local skill are the reviewable strategic-control package.
- This AI_CONTROL package gives Codex and external GPT a compact strategic review loop.
- The strategic control pack from `<local-user-home>/Downloads/codex_strategic_control_pack` was implemented by adding `STRATEGIC_OPERATING_SYSTEM.md`, strategic state/review templates, repo/global append rules, and a `strategic-autonomy-review` skill in both repo and user skill locations.
