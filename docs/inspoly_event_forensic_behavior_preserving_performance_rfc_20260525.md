# Event Forensic Behavior-Preserving Performance RFC

Date: 2026-05-25

Status: RFC only. No performance runtime patch was implemented.

Gate: `needs_more_measurement`

## Current Evidence

The existing local performance inventory shows large whole-event runs and known bottlenecks in trade collection and wallet/funding context loading. The current campaign could not run a bounded live measurement because read-only env/config was unavailable.

## Safe Optimization Candidates

The following remain potentially safe only after bounded measurement:

- cache repeated pure context normalization within one run;
- avoid duplicate local parsing of already-collected report/snapshot payloads;
- improve timing instrumentation consistency;
- reuse replay snapshot payloads for local review.

## Blocked Optimization Types

Do not implement:

- candidate skipping;
- reduced market coverage;
- changed fetch limits;
- changed ranking or scoring;
- changed thresholds, Strong Risk/HER/funding/candidate gates;
- storage schema changes.

## Required Proof Before Runtime Patch

Any behavior-preserving patch must prove:

- same candidate IDs on fixtures;
- same scores on fixtures;
- same review buckets except already-approved policy behavior;
- same selected-market vs whole-event scope;
- no storage/UI sorting changes.

## Decision

No safe runtime optimization is approved from local evidence alone. Next step is bounded measurement, then a narrow implementation RFC if evidence supports it.
