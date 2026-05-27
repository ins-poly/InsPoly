# InsPoly Donor Remaining Three-Branch Decision

Date: 2026-05-27 EEST

Final combined gate: `three_branch_execplan_no_safe_runtime_changes`

## Branch Decisions

| Branch | Gate decision | Runtime changed? | Next approval question |
| --- | --- | --- | --- |
| A: indexer / warehouse | `indexer_live_blocked_needs_operator_approval` | No | Should an operator approve one bounded live sidecar run with explicit targets and SQLite output DB? |
| B: sidecar context reports/UI | `sidecar_context_report_pointer_rfc_ready` plus `sidecar_context_keep_sidecar_only_final` | No | Should product approve pointer-only report metadata, or keep all context sidecar-only? |
| C: pUSD/CLOB collateral and Phase 3 | `pusd_collateral_research_rfc_ready`; `phase3_runtime_still_blocked` | No | Should verified address/source research begin, and should formula-derived SELL max loss ever be product-approved without a direct collateral field? |

## What Changed

- Added a read-only indexer sidecar DB readiness audit tool and tests.
- Added static pUSD/CLOB collateral semantics helper, fixture, and tests.
- Added branch evidence reports and compact JSON summaries.
- Updated strategic state and memory locally.

## What Did Not Change

- No production scanner/archive/Event Forensic/browser/storage imports.
- No scoring, gates, labels, routing, funding eligibility, candidate admission, or sorting changes.
- No Phase 3 runtime.
- No pUSD/funding runtime integration.
- No storage schema migration.
- No report writer/loader or UI panel.
- No live indexer, background worker, or automatic startup.
- No CLOB auth, private keys, trading, or order placement.
- No push or PR.

## Next Three-Campaign Roadmap

1. Bounded live indexer approval packet: choose one target set, caps, timeout, and SQLite output DB; run only after operator approval.
2. Sidecar report-pointer product decision: decide whether reports may point to sidecar artifacts without copying metrics.
3. pUSD/collateral verified-source research: collect official/verified address facts into static fixtures, then reassess Phase 3 source-field blockers.

## Final Decision

All three branches are now decision-ready as RFC/sidecar work. None is approved for runtime integration.
