# Operations Guide

This guide covers safe local use.

All commands assume the current directory is the repository root.

## First Run

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
cp .inspoly_runtime.env.example .inspoly_runtime.env
inspoly desktop
```

Expected behavior:

- a local Python process starts;
- the app opens or serves a browser UI on your machine at a tokenized `127.0.0.1` URL;
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

This is also the default when no runtime env file is present. Use `live_rpc` only as an explicit opt-in.

Optional LLM review is controlled by `INSPOLY_LLM_PROVIDER`, `INSPOLY_LLM_MODEL`, and `OPENAI_API_KEY`. It is advisory only. When enabled, selected case-packet context is sent from the local machine to the configured external provider.

## Running The Programs

Recent scanner:

```bash
inspoly desktop
```

Archive researcher:

```bash
inspoly archive-desktop
```

Event forensic analyzer:

```bash
inspoly event-desktop
```

Native macOS app:

```bash
python3 -m pip install -e ".[macos-app]"
python3 -m app macos-app
```

Local fallback bundle:

```bash
tools/build_macos_app.sh
```

Local DMG build:

```bash
tools/build_macos_release.sh
```

This writes `dist/release/InsPoly.dmg` and `dist/release/InsPoly.dmg.sha256` without Apple login/password setup. The default artifact is local/ad-hoc signed and may show Gatekeeper warnings on another Mac.

Optional notarization is separate and uses only an existing `notarytool` keychain profile:

```bash
export INSPOLY_MACOS_SIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)"
export INSPOLY_NOTARYTOOL_PROFILE="inspoly-notary-profile"
tools/build_macos_release.sh --notarize
```

The release script does not accept Apple ID/password environment variables. Do not commit signing identities, keychain profile setup notes, or generated release artifacts.

`InsPoly.app` includes a keep-awake toggle for active analysis. It prevents idle system sleep while a scan/export/analysis is running. It does not override explicit Sleep, lid close, low battery, shutdown, or other macOS power decisions.

CLI recent scan:

```bash
inspoly scan --lookback 4h --categories "Politics,World,Ukraine,Middle East"
```

Wallet inspection:

```bash
inspoly inspect-wallet --address 0x0000000000000000000000000000000000000000
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
python3 -m compileall app tools tests
python3 tools/public_repo_checks.py --all
tools/validate_macos_release.sh
```

## Clean Clone Verification

This is the recommended check before sharing a branch or after cloning on a new machine:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
python3 -m app --help
inspoly --help
python3 -m app scan --help
python3 -m app inspect-wallet --help
python3 -m compileall app tools tests
python3 -m unittest discover -s tests -p 'test_*.py'
python3 tools/public_repo_checks.py --all
```

For Event Forensic performance work after packaging, start with read-only measurement:

```bash
tools/run_event_forensic_performance_probe.sh
```

Current expected result:

- install succeeds without private local files;
- help commands print usage text;
- compile succeeds;
- the test suite and repository hygiene checks pass.

The public CLI entry path is `inspoly ...`. `python3 -m app ...` remains supported for repository-local use.

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
