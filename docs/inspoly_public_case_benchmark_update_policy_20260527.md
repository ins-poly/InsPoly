# InsPoly Public-Case Benchmark Update Policy

Date: 2026-05-27

Base commit: `82fbfab` - `Add public-case evidence bridge`

Runtime changed: `false`

Push/PR performed: `false`

## Decision

Exact-wallet public benchmark upgrades require an accepted source-backed intake label.

Current public controls remain non-exact:

- `named_user_only` stays a named-user source control, not a wallet assertion.
- `pattern_level_only` stays a pattern or cluster control, not wallet recall evidence.
- `market_level_only` stays a market/event control, not user or wallet evidence.
- `named_user_local_wallet_candidate` is a review candidate tier only and cannot be accepted as exact-wallet truth.

## Intake Requirement

Future exact-wallet additions must start from a JSON intake file matching:

- `tests/fixtures/known_case_benchmark/public_case_label_intake_schema.json`

The intake must pass:

- `tools/public_case_label_intake_validator.py`

Passing validation does not automatically update the benchmark. It only means the intake is complete enough for a separate fixture update campaign.

## Required Evidence For Exact Wallet Labels

An accepted exact-wallet label must include:

- `proposed_assertion_level: exact_wallet_supported`
- full `wallet_address`
- `market_slug` or `condition_id`
- source URLs and titles
- short evidence summary
- timestamp/date for the evidence
- curator identity
- `confidence: fixture_grade`
- `review_status: accepted`
- `accepted_for_benchmark: true`
- limitations
- forbidden interpretation

At least one evidence path must prove wallet identity:

- public source explicitly publishes the full wallet and market/user context; or
- public source names a user/account and a local artifact proves user-to-wallet mapping; or
- transaction/source trail ties named entity, wallet, market, and condition together; or
- human curator supplies documented proof with source URL/path and timestamp.

## Rejection Rules

Reject exact-wallet upgrades when evidence is only:

- timing inference;
- high score or local model output;
- unnamed cluster report;
- market-level source without wallet identity;
- partial wallet snippet;
- screenshot without reproducible source or local reconciliation;
- "likely same user" language without proof;
- local review packet row that does not link public identity to wallet identity.

## Fixture Update Requirements

Every future exact-wallet fixture addition must include:

- updated benchmark fixture fields;
- source/provenance notes;
- `forbidden_interpretation`;
- rollback note;
- tests proving exact-wallet fields are present;
- no automatic action or scoring-claim permission unless a separate approved model campaign changes that policy.

## What Must Not Change From Intake Alone

- no runtime/model/scoring/gate behavior;
- no Strong Risk/HER/funding/candidate admission behavior;
- no Phase 3 runtime;
- no storage schema;
- no UI sorting/filtering;
- no saved artifact mutation;
- no production use of unaccepted labels.

## Current Gate

`public_case_human_labeling_packet_ready`

The next allowed step is human/source review using the packet. Benchmark upgrades remain blocked until accepted intake evidence exists.
