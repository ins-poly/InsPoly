# InsPoly RC V4 Not Included / Still Blocked - 2026-05-28

## Not Included In RC V4

- GitHub CI workflow setup.
- Production warehouse daemon, scheduler, or background worker.
- Live indexer integration into scanner/archive/Event Forensic/browser runtime.
- Browser UI panels for sidecar warehouse data.
- Copied warehouse metrics in reports.
- Row-level sidecar context in reports.
- Phase 3 capital-at-risk runtime.
- pUSD/CLOB collateral funding runtime.
- CLOB auth, private keys, trading, or order placement.
- Production storage schema migration.
- Saved report mutation.
- Report sorting/filtering changes.

## Still Blocked

| Area | Gate |
| --- | --- |
| Phase 3 capital runtime | blocked pending stronger source fields and explicit product/accounting decision |
| pUSD/CLOB funding runtime | blocked pending source-grade addresses and tracing policy |
| Warehouse runtime | blocked pending separate implementation approval |
| Scheduler/background mode | blocked pending separate operator approval |
| Browser warehouse UI | blocked pending product approval |
| Copied warehouse metrics | rejected for RC V4 |
| Production pagination expansion | RFC-only until provider/query proof improves |
| Exact-wallet public labels | blocked until accepted human/source labels exist |

## Safe RC V4 Interpretation

RC V4 improves local analysis, report compatibility, browser offline readiness, benchmark coverage, sidecar warehouse review tooling, and optional pointer metadata. It does not convert sidecar evidence into production scoring or UI behavior.
