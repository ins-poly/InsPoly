# Future W1 Manual Local Warehouse Command Approval Packet - 2026-05-27

## Status

Approval packet status: `ready_for_owner_review`.

Implementation status: not approved and not implemented.

W1 must be a future separate campaign. This packet defines what the owner would be approving if they choose to proceed.

## Exact W1 Scope

W1 may add a manual local command that writes approved bounded public indexer data into an explicit local sidecar warehouse SQLite DB.

Allowed W1 command behavior:

- manual CLI invocation only;
- explicit config file required;
- target registry or exact market slugs required;
- config validation before any live/network path;
- public read-only Gamma/Data API calls only if explicitly approved for that run;
- per-target public-trade caps plus aggregate safety caps;
- local SQLite sidecar output only;
- compact run summary, readiness audit, and scoped compare output;
- no saved report mutation;
- no production runtime imports.

## Not Approved In W1 By Default

W1 must not include:

- automatic startup;
- daemon, scheduler, background worker, or repeat loop;
- warehouse append mode unless explicitly listed in the W1 config and separately approved;
- report writer/browser integration;
- production scanner/archive/Event Forensic imports;
- production storage schema migration;
- scoring/gate/HER/funding/candidate-admission changes;
- Phase 3 runtime;
- CLOB auth, private keys, signatures, trading, order placement, or external writes.

## Local DB And Output Policy

Default output should be under:

- `.inspoly_indexer/warehouse_w1_<date>/`
- or another operator-approved local sidecar path.

Raw DBs remain local-only by default. Compact summaries and validation JSON may be committed only when intentionally staged.

W1 must reject remote/service output paths such as HTTP, S3, Postgres, Redis, or hosted DB URLs.

## Target Registry Policy

W1 should use one of:

- an explicit approved target registry JSON;
- an exact approved market slug list.

No wildcard, category, broad event-family, or automatic target discovery is allowed by default.

Target metadata required before live collection:

- input slug;
- canonical market slug;
- condition ID;
- market/event ambiguity classification;
- expected market row count;
- allowed cap profile;
- whether the target is an anchor, replacement candidate, sparse control, or rejected target.

## Config Validator Requirements

W1 config validation must reject:

- missing targets;
- wildcard targets;
- target count beyond approval;
- missing or unsafe SQLite path;
- production integration flags;
- warehouse mode outside the approved W1 command;
- auto-start/background/scheduler flags;
- saved artifact mutation;
- auth/private-key/trading/order-placement fields;
- unsafe per-target and aggregate caps.

The validator must record that operator approval is still required for live execution.

## Retention

W1 must define:

- fresh DB versus append-mode behavior;
- max retained DB count or manual deletion policy;
- max local bytes or operator warning threshold;
- raw DB local-only default;
- compact summary retention;
- rollback by deleting the local sidecar output directory.

Append mode should remain blocked unless the W1 campaign explicitly approves and tests it.

## Rollback

Rollback must be local-only:

1. Stop invoking the W1 command.
2. Delete the local sidecar warehouse output directory.
3. Preserve scanner/archive/Event Forensic/browser/report storage unchanged.
4. Revert W1 sidecar code if needed.

No saved report or production runtime rollback should be required.

## Validation Required Before W1 Completion

Minimum validation:

- JSON validation for compact outputs;
- `py_compile` for changed helper/tool/test files;
- focused tests for W1 command, config validator, storage, readiness audit, DB compare, and warehouse contract helper;
- runtime import scan proving no scanner/archive/Event Forensic/browser/report production imports;
- local output-path tests;
- no-network tests for config validation and dry-run modes;
- readiness audit against generated fixture DBs;
- scoped compare tests for repeat/append behavior if append mode is approved;
- `git diff --check` and staged diff check before commit.

## W1 Stop Conditions

Stop immediately if:

- W1 needs production runtime integration;
- W1 needs report/browser changes;
- W1 requires production storage migration;
- live scope exceeds approved targets/caps;
- append mode requires schema migration not approved by W1;
- any auth/private-key/trading/external write field appears;
- background worker/scheduler/daemon behavior appears;
- saved report mutation appears;
- `.inspoly_indexer/` raw DBs would need to be committed.

## What Remains Blocked After W1

Even if W1 succeeds, these remain blocked:

- scheduled/background warehouse mode;
- production runtime imports;
- report pointer or browser panel integration;
- copied metrics in saved reports;
- scoring/gate/funding/Phase 3 use;
- broad target discovery;
- hosted service storage;
- CLOB auth/trading behavior.

## Approval Question

Owner decision needed:

Approve a future W1 campaign to implement one manual local warehouse command under the W0 contracts, with no automatic runs and no production integration?

Recommended default if approved: start with a no-network fixture implementation and generated local DB tests before any live run is separately approved.
