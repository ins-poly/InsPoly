# InsPoly Event Forensic Weak-History Live/RPC Operator Plan

- Date: 2026-05-22
- Scope: operator plan only
- Runtime implementation: false
- Network/RPC executed now: false
- Gate decision: `live_rpc_plan_ready_not_executed`

## Purpose

Validate the remembered Event Forensic risk: weak economic history wallets with near-certain later-winning entries can rank in ways that local saved reports do not fully prove. The goal of a future approved run is measurement only.

## Why Local Reports Are Insufficient

The saved-report audit found 8 sufficient real weak-history near-certain later-win rows, but many saved rows lack weak-history or winner-rank fields. That is enough for a contract replay, not enough for a current distribution claim.

## Bounds For A Future Approved Run

- Max events: 3.
- Max markets per event: 8.
- Max candidate wallets per market: 150.
- Max total trade rows loaded: 50,000.
- Max wall time: 30 minutes.
- Output directory: timestamped directory under `validation_outputs/event_forensic_weak_history_live_rpc_*/`.
- No mutation of saved reports, storage schema, browser state, or production reports.

## Required Environment

- Existing InsPoly configuration only.
- RPC/network variables already supported by the app, if operator-approved.
- No private keys, CLOB auth, trading credentials, or order-placement configuration.

## Expected Commands

The future operator run should use existing Event Forensic CLI/application paths with explicit output directory and no persistence mutation beyond the new validation output directory. The command must be reviewed immediately before execution because live/RPC entry points are intentionally not invoked in this campaign.

## Allowed Comparison

- Saved-report versus freshly collected weak-history near-certain later-win rows.
- Event Forensic rank, `laterWon`, `winnerRank`, weak-history flags/reducers, economic probability, and selected-market/event scope metadata.
- Phase 2/4 semantic consistency.

## Forbidden During Validation

- Scorer tuning.
- Phase 3 capital-at-risk implementation.
- Strong Risk/HER/funding/candidate-admission gate changes.
- UI sorting/filtering changes.
- Storage schema changes.
- Broad crawling or unbounded event discovery.
- Private keys, trading, CLOB auth, or order placement.

## Stop Conditions

Stop immediately if the run requires broader crawling, scorer tuning, Phase 3, direct gate changes, storage changes, UI behavior changes, or credentials beyond read-only public/RPC access.

## Rollback / No-Op Strategy

The approved run should create only a new timestamped validation directory. Rollback is deleting that output directory. Runtime code and saved reports must remain unchanged.
