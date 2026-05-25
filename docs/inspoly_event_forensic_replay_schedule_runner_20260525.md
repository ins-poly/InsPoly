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
