# InsPoly Event Forensic Event-Level Semantics RFC

- Date: 2026-05-22
- Scope: RFC-only event-level semantics guardrail
- Machine output: `validation_outputs/inspoly_event_forensic_event_level_semantics_rfc_20260522.json`
- Runtime implementation in this program: false
- Network/RPC used: false
- Gate decision: `event_level_semantics_rfc_ready_no_runtime`

## Problem

Event Forensic can be interpreted incorrectly when a selected child market belongs to a broader event family. Side/Outcome normalization clarifies trade direction, but it does not decide whether primary scoring should be selected-market-only or whole-event.

Current status from local validation: `still_architecture_ambiguity`.

## Current Contract

- Single-market reports keep primary scoring scoped to the selected market.
- Related/sibling markets may appear as context, but they must not silently broaden primary scoring.
- Whole-event reports may score sibling/related markets as primary scope only when explicitly requested.
- Side/Outcome economic direction is a direction semantic, not an event-scope semantic.

## Proposed Semantics

### Single-Market Mode

Primary ranking, later-correctness, and candidate visibility remain tied to the selected market. Related markets can be shown as context only.

### Whole-Event Mode

Primary ranking may include all markets in the explicit event family. Reports must clearly identify event-wide scope.

### Related-Market Context

Related markets may explain alternative exposure or market-family behavior, but cannot silently change candidate admission, scoring, sorting, or report visibility.

## Required Tests Before Runtime Change

- Single-market report keeps sibling markets out of primary ranking.
- Whole-event report explicitly marks event-wide scope.
- Related-market context cannot change selected-market scoring.
- Old reports without scope metadata load absent-safe.
- Browser labels distinguish selected-market and whole-event scope before any UI behavior change.

## Stop Conditions

Stop before implementation if a proposal requires:

- silent single-market broadening;
- scoring weight/threshold changes;
- candidate admission changes;
- Strong Risk/HER/funding changes;
- UI sorting/filtering changes without product approval;
- live/RPC access without explicit approval.

## Gate Decision

Decision: `event_level_semantics_rfc_ready_no_runtime`.

This RFC is ready as a planning guardrail. Runtime scope changes still require separate approval.
