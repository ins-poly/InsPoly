# InsPoly Known-Case Benchmark Maintenance Checklist

Date: 2026-05-27

Base commit: `90e2434` - `Add public-case human labeling packet`

Runtime changed: `false`

Live/RPC used: `false`

Push/PR performed: `false`

Gate decision: `known_case_benchmark_maintenance_ready`

## Current State

The known-case benchmark corpus contains 30 compact cases:

| Metric | Count |
|---|---:|
| total known-case corpus | 30 |
| public controls | 6 |
| exact-wallet public cases | 0 |
| named-user local wallet candidates | 0 |
| named-user-only public cases | 2 |
| pattern-level-only public cases | 2 |
| market-level-only public cases | 2 |
| public cases requiring human review | 6 |
| false-positive controls | 4 |
| sidecar/context controls | 4 |

The public exact-wallet upgrade path is intentionally blocked until a future source-backed intake label is accepted. The active intake contract is:

- `tests/fixtures/known_case_benchmark/public_case_label_intake_schema.json`
- `tools/public_case_label_intake_validator.py`
- `docs/inspoly_public_case_human_labeling_packet_20260527.md`
- `docs/inspoly_public_case_benchmark_update_policy_20260527.md`

## How To Add A New Non-Public Case

1. Confirm the case is compact enough for a fixture and does not require raw report imports.
2. Add a unique `case_id` under `tests/fixtures/known_case_benchmark/post_side_outcome_known_cases.json`.
3. Include the smallest fields needed to exercise the intended contract.
4. Include provenance fields that explain whether the case is synthetic, local-artifact-supported, sidecar-only, or advisory.
5. Include `expected_behavior` and `forbidden_interpretation` when the case could be overread.
6. Add or update tests for schema validation, duplicate IDs, and the relevant assertion type.
7. Run the known-case benchmark tests before committing.

## How To Add A Public-Source Case

1. Record source URLs, titles, dates, and concise source notes only. Do not commit article text.
2. Choose the weakest accurate assertion level:
   - `exact_wallet_supported`
   - `named_user_local_wallet_candidate`
   - `named_user_only`
   - `pattern_level_only`
   - `market_level_only`
   - `insufficient_source_evidence`
   - `defer_needs_human_label`
3. If the public source does not prove exact wallet identity, do not assert exact wallet recall.
4. Add `forbidden_interpretation` for every non-exact public case.
5. Add `human_review_needed: true` when exact-wallet evidence is missing.
6. Keep public cases advisory unless a separate accepted intake label supports an exact-wallet upgrade.

## How To Process Human Label Intake

1. Ask the human reviewer to fill a JSON intake matching `public_case_label_intake_v1`.
2. Validate the intake with `tools/public_case_label_intake_validator.py`.
3. Treat a passing validator result as completeness only, not benchmark acceptance.
4. Review whether the evidence proves wallet/user/market identity without inference.
5. If accepted, run a separate fixture update campaign with rollback notes and tests.
6. If rejected or incomplete, keep the benchmark case at its current assertion level and record the deferred reason.

## Evidence That Must Be Rejected For Exact-Wallet Upgrades

Reject exact-wallet upgrades based only on:

- timing inference;
- unnamed cluster reporting;
- market-level reporting without wallet identity;
- partial wallet snippets without reconciliation;
- local heuristic scores;
- local review routing;
- "likely same user" language;
- article screenshots or summaries without reproducible source and local reconciliation.

## Required Fields

Every benchmark case needs:

- unique `case_id`;
- assertion type/category;
- source or fixture provenance;
- expected behavior;
- explicit forbidden interpretation when advisory, public, sidecar-only, or false-positive oriented.

Every public-source case additionally needs:

- `source_urls`;
- `source_titles`;
- `source_dates` where available;
- `assertion_level`;
- `evidence_quality`;
- `identity_confidence`;
- `human_review_needed` when exact-wallet proof is missing;
- `deferred_reason` when exact-wallet upgrade is not supported.

Every future accepted exact-wallet public case must include:

- full wallet address;
- market slug or condition ID;
- source-backed identity proof;
- `confidence: fixture_grade`;
- `review_status: accepted`;
- `accepted_for_benchmark: true`;
- limitations and rollback notes.

## Fixture Compactness Rules

- Do not import bulky raw reports, articles, live output directories, or review packet directories.
- Prefer compact metadata and source pointers.
- Keep local artifact refs path-like and narrow.
- Do not copy long copyrighted article text.
- Do not commit generated evidence dumps as benchmark fixtures.

## Required Tests

Run at minimum:

- public-case intake validator tests when intake schema/tooling changes;
- known-case benchmark tests after fixture changes;
- benchmark schema tests after assertion-level or required-field changes;
- public-case evidence bridge tests after public evidence-tier changes;
- `git diff --check`;
- JSON validation for new or changed JSON outputs.

Run the full suite when:

- the benchmark runner changes broadly;
- shared schema behavior changes;
- a fixture change affects multiple assertion types;
- production runtime paths change.

## Rollback Plan

- Fixture-only rollback: revert the fixture/test/doc commit.
- Accepted-label rollback: revert the exact-wallet fixture update and restore the previous assertion level.
- Tooling rollback: revert validator/schema changes, then re-run the previous known-case tests.
- Runtime rollback should not be needed from benchmark maintenance work because benchmark maintenance must not modify runtime paths.

## Forbidden Overclaims

- A public-source case is not exact-wallet evidence unless the source or accepted intake proves it.
- Pattern-level cases cannot test exact wallet recall.
- Market-level cases cannot test user or wallet detection.
- Named-user-only cases cannot prove Polymarket wallet identity.
- Passing intake validation does not apply a benchmark label.
- Benchmark expansion does not authorize model, scoring, routing, gate, Phase 3, storage, or UI behavior changes.

## Current Maintenance Gate

`known_case_benchmark_maintenance_ready`

The next allowed benchmark work is either:

- use the existing 30-case corpus as a validation guardrail before future runtime/model-adjacent work; or
- process a future human label intake and run a separate fixture update campaign if source-backed exact-wallet evidence is accepted.
