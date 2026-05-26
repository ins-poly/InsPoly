# Event Forensic Wallet API Boundary Batching RFC

Date: 2026-05-26

## Status

Gate: `wallet_api_boundary_batching_rfc_needed`

This RFC is a planning document only. It does not approve runtime implementation.

## Evidence

The scorer-context prepared-context patch reduced score-loop cost on the approved high-density subset, but total runtime did not improve because wallet prefetch/API time remains comparable to score time.

Latest bounded subset measurement:

- Event: `us-x-iran-permanent-peace-deal-by`
- Scope: 6 selected markets out of 15 live markets
- Candidate rows: 15,354
- Candidate wallets: 3,292
- Total runtime: 678.99s
- Score loop: 318.00s
- Wallet prefetch/context: 303.42s
- Prepare candidate context: 17.17s

This is subset-only performance evidence, not whole-event completeness evidence.

## Problem

Current Event Forensic prefetch remains sensitive to one-context-per-wallet loading and live/API variance. The existing run-local caches preserve behavior but operate after wallet context is fetched. They cannot reduce the upstream API boundary cost.

## Candidate Patch Options

Allowed future options:

- Batch wallet stats/position requests only if the underlying API/client already supports equivalent read-only batch semantics.
- Deduplicate wallet context requests before any network call.
- Reuse isolated validation cache entries within a single run without changing stale/failure semantics.
- Add finer timing around stats versus positions fetches.
- Add operator budget warnings when unique candidate wallets exceed measured safe ranges.

Forbidden options:

- Skipping candidate wallets.
- Reducing wallet coverage.
- Changing candidate admission, scores, ranks, review buckets, or exports.
- Changing funding trace semantics or treating unknown funding as absent.
- Changing pagination or selected-market/whole-event scope in the same patch.
- Introducing persistent storage schema changes.
- Adding CLOB auth, private keys, trading, or order placement.

## Required Proof

Before implementation:

- Static equivalence on saved high-density subset.
- Candidate IDs unchanged.
- Scores unchanged.
- Rank order unchanged.
- Review buckets and weak-history demotion unchanged.
- Export rows unchanged.
- Old report compatibility unchanged.
- Live measurement must separate API variance from code behavior.

## Stop Conditions

Stop if batching would require changing source precedence, missing-data fallback, request bounds, candidate filters, or storage schema. Stop if API behavior is not equivalent to existing per-wallet reads.

## Rollback

Rollback must restore the current per-wallet prefetch path and remove only batching/timing metadata. It must not require saved artifact mutation or storage migration.
