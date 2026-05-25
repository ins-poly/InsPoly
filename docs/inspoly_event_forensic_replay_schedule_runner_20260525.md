# Event Forensic Replay Schedule Runner

Date: 2026-05-25

Gate: `replay_schedule_sidecar_ready`

Machine-readable output:

- `validation_outputs/event_forensic_replay_schedule_plan_20260525.json`

## What Was Added

`tools/event_forensic_replay_schedule_runner.py` builds a local replay schedule plan from an existing replay snapshot. It creates planned stages:

- `initial`
- `+1h`
- `+4h`
- `+24h`

## What It Does Not Do

- It does not start a background scheduler.
- It does not call live/RPC/network paths.
- It does not mutate app storage.
- It does not rerun Event Forensic analysis.
- It does not change scores, gates, thresholds, or UI behavior.

## Validation

The generated plan preserved whole-event/selected-market scope metadata and candidate count metadata from the source snapshot.

## Next Gate

Real scheduled replay persistence would require either explicit operator workflow approval or a storage RFC. The sidecar plan path is ready for local review.

## 2026-05-25 Measurement Follow-Up

Gate: `replay_schedule_updated_with_timing_budget`

The first bounded performance precheck did not produce completed timing data because the selected event resolved to 15 live markets and exceeded the 8-market measurement cap.

The follow-up safe-target run completed on `russia-x-ukraine-ceasefire-by-january-31-2026`:

- Total runtime: 20.54 seconds
- Raw rows: 3,208
- Candidate rows: 144
- Candidate wallets: 83
- Dominant bottleneck: `collect_event_trades_seconds`

`tools/event_forensic_replay_schedule_runner.py` now accepts an optional bounded measurement summary and records planned-only performance-budget metadata. It still does not start a scheduler, call live/RPC, mutate storage, or change Event Forensic behavior.

## 2026-05-25 Expansion Follow-Up

Gate: `replay_schedule_updated_with_timing_budget`

The measurement expansion added two more completed bounded samples and an aggregate output:

- Measurements: 3
- Median runtime: 20.54 seconds
- Slowest runtime: 22.44 seconds
- Completed sample scope: all single-market events

This improves the small-target duration baseline, but it does not justify a broader automatic replay budget for large whole-event runs. Replay schedule planning remains sidecar-only and should label any future larger-event subset replay as subset-only unless whole-event scope is explicitly approved and measured.
