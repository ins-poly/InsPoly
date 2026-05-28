# Browser Strict Offline Asset Implementation

Date: 2026-05-26

Gate decision: `browser_strict_offline_ready`

Runtime/model behavior changed: `false`

Browser boot behavior changed: `true`

Push/PR performed: `false`

## Summary

Implemented the approved narrow strict-offline browser asset strategy without rewriting the browser UI or introducing a build pipeline.

Both browser HTML surfaces now boot from local pinned runtime assets:

- `app/browser_ui.html`
- `app/browser_event_forensic_ui.html`

Both local browser servers now serve only approved files under `/vendor/browser/`:

- `app/browser_desktop.py`
- `app/event_forensic_desktop.py`

No scoring/model/gate, Phase 3, storage schema, saved artifact, UI sorting/filtering, trading, CLOB auth, or private-key behavior changed.

## Vendored Runtime Assets

| Package | Version | Local path | Source URL | SHA-256 | Size |
|---|---:|---|---|---|---:|
| React | `18.3.1` | `app/vendor/browser/react/18.3.1/react.development.js` | `https://unpkg.com/react@18.3.1/umd/react.development.js` | `28348fef6cb0ed8b2ceeb22deaf824428fd13875d84c73d38f77dd216fc24e7f` | 109,931 bytes |
| ReactDOM | `18.3.1` | `app/vendor/browser/react-dom/18.3.1/react-dom.development.js` | `https://unpkg.com/react-dom@18.3.1/umd/react-dom.development.js` | `f9044a5e9c39db8bb1a204dff924e526ec0a621e695bb69de1035811be8709e4` | 1,080,227 bytes |
| Babel standalone | `7.29.7` | `app/vendor/browser/babel-standalone/7.29.7/babel.min.js` | `https://unpkg.com/@babel/standalone@7.29.7/babel.min.js` | `7f55bd5c3efadeaa83d4de97dc91da8bf0733789801cf28b9273c4284739798e` | 3,140,250 bytes |

Provenance is recorded in:

- `app/vendor/browser/PROVENANCE.json`

No source maps, examples, package directories, or font assets were vendored.

## Static Serving

Added `app/browser_static_assets.py` as the shared static serving boundary for browser runtime assets.

The helper:

- serves only paths under `/vendor/browser/`;
- maps those paths to `app/vendor/browser/`;
- rejects path traversal, including encoded traversal;
- returns narrow MIME types for JavaScript, JSON, CSS, and font extensions;
- does not expose reports, config, environment variables, arbitrary filesystem paths, or saved artifacts.

Both browser launchers call this helper before their existing API routes. Existing `/`, `/api/bootstrap`, `/api/run`, scan/analyze APIs, output-open APIs, and report-loading behavior remain unchanged.

## HTML And Font Policy

The two browser HTML files now load:

- `/vendor/browser/react/18.3.1/react.development.js`
- `/vendor/browser/react-dom/18.3.1/react-dom.development.js`
- `/vendor/browser/babel-standalone/7.29.7/babel.min.js`

Runtime Babel remains in place because the current UI still uses inline `type="text/babel"` scripts. Removing runtime Babel remains a future build-pipeline/refactor decision.

Google Fonts links were removed for strict offline mode. CSS now keeps the preferred font names but adds local system fallbacks. No font files were vendored.

## Remaining Network Dependencies

No network is required for browser boot.

Remaining network references are analyst navigation links only, such as Polygonscan or Polymarket profile/event links embedded in UI actions. They are not required to load the app or local reports.

## Readiness Tooling

Updated strict-offline readiness tooling to verify:

- local React, ReactDOM, and Babel files exist;
- SHA-256 and byte sizes match the provenance manifest;
- both browser HTML files use local boot scripts;
- no hard remote boot script remains;
- no Google Fonts stylesheet remains;
- both browser desktop servers serve static vendor assets safely;
- inline Babel is acceptable because the local Babel runtime is present.

Implementation output:

- `validation_outputs/inspoly_browser_strict_offline_asset_implementation_20260526.json`

## Rollback

Rollback is local and mechanical:

1. Restore prior HTML script/font references.
2. Remove `app/browser_static_assets.py` imports and route checks from both desktop launchers.
3. Remove `app/vendor/browser/` assets and provenance if cleanup is explicitly approved.
4. Restore strict-offline readiness expectations to the blocked asset-policy state.

No model, storage, scoring, saved report, or artifact rollback is needed.

## Final Decision

Gate: `browser_strict_offline_ready`.

Strict offline boot is ready for both current browser UIs using local pinned runtime assets. Future work may still remove runtime Babel or add a build pipeline, but that is not required for strict offline boot and was not done here.
