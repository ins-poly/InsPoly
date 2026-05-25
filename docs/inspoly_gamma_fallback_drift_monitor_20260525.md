# Gamma Fallback Drift Monitor

Date: 2026-05-25

Gate: `gamma_fallback_monitor_ready`

Machine-readable output:

- `validation_outputs/gamma_fallback_drift_monitor_20260525.json`

## What Was Added

`tools/gamma_fallback_drift_monitor.py` checks saved `__NEXT_DATA__` payload shapes used by the Polymarket Gamma fallback path.

Fixture:

- `tests/fixtures/gamma_fallback/next_data_event_market.html`

## Result

The saved fixture matches the current expected shape:

- query slug list present;
- event query payload present;
- source market can be found inside the event payload.

## What It Does Not Do

- It does not fetch Polymarket pages.
- It does not change resolver behavior.
- It does not change scanner/archive/Event Forensic runtime paths.

## Remaining Risk

This monitor covers the local expected shape only. A future live check may still be needed if Polymarket frontend payload structure changes.
