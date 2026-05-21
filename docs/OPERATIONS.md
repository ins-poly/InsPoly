# Operations Guide

This guide covers safe local use.

All commands assume the current directory is the repository root.

## First Run

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
cp .inspoly_runtime.env.example .inspoly_runtime.env
python3 -m app desktop
```

Expected behavior:

- a local Python process starts;
- the app opens or serves a browser UI on your machine;
- runtime state and reports are written only to local ignored directories;
- no hosted backend is required from this repository.

## Runtime Modes

Funding trace mode is controlled by `INSPOLY_FUNDING_TRACE_MODE`:

- `disabled`: do not call Polygon RPC; funding evidence is unknown.
- `cache_only`: read existing local cache only; misses are unknown.
- `live_rpc`: use configured Polygon RPC endpoints.

For first-time local runs, start with:

```text
INSPOLY_FUNDING_TRACE_MODE=disabled
```

## Running The Programs

Recent scanner:

```bash
python3 -m app desktop
```

Archive researcher:

```bash
python3 -m app archive-desktop
```

Event forensic analyzer:

```bash
python3 -m app event-desktop
```

CLI recent scan:

```bash
python3 -m app scan --lookback 4h --categories "Politics,World,Ukraine,Middle East"
```

Wallet inspection:

```bash
python3 -m app inspect-wallet --address 0x0000000000000000000000000000000000000000
```

## Outputs To Expect

Do not be surprised when local report directories appear. They are part of the workflow.

Typical directories:

- `.inspoly/`
- `.inspoly_archive_researcher/`
- `.inspoly_event_forensic_analyzer/`
- `outputs/`
- `archive_outputs/`
- `event_forensic_outputs/`
- `*_outputs/`

These are ignored by git.

## Test Commands

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m py_compile app/*.py tools/*.py tests/*.py
```

## Clean Clone Verification

This is the recommended check before sharing a branch or after cloning on a new machine:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
python3 -m app --help
python3 -m app scan --help
python3 -m app inspect-wallet --help
python3 -m py_compile app/*.py tools/*.py tests/*.py
python3 -m unittest discover -s tests -p 'test_*.py'
```

Current expected result:

- install succeeds without private local files;
- help commands print usage text;
- compile succeeds;
- the test suite passes, with the repository's expected-failure tests still reported as expected failures.

The CLI entry path is `python3 -m app ...`. The project metadata name is `inspoly`, but there is no separate `inspoly` shell command.

## Common Failure Modes

Polymarket API issue:

- Symptoms: empty results, HTTP errors, changed payload shapes, slow scans.
- Response: retry later, narrow the scope, inspect API response handling before changing scoring.

Polygon RPC issue:

- Symptoms: funding unavailable, auth errors, rate limits, stalled traces.
- Response: keep funding state as `unknown`; do not claim no funding evidence.

Large event issue:

- Symptoms: slow event forensic runs, trade pagination limits, truncated markets.
- Response: use exact child-market scope when appropriate; avoid lowering detection thresholds just to improve runtime.

Legacy report issue:

- Symptoms: old saved report reopens with missing display rows or older labels.
- Response: preserve compatibility normalization unless old reports are deliberately migrated.
