# InsPoly Browser Strict Offline Readiness

Date: 2026-05-26

Gate: `browser_offline_blocked_requires_asset_policy`

## Scope

This review audited strict offline boot readiness for the browser-facing analyst surfaces without changing browser behavior:

- `app/browser_ui.html`
- `app/browser_event_forensic_ui.html`
- `app/browser_desktop.py`

No external assets were downloaded or vendored. No browser UI labels, sorting, filtering, report semantics, scoring, gates, storage schema, saved artifacts, or Phase 3 runtime paths were changed.

## Current Dependency Inventory

Machine-readable inventory:

- `validation_outputs/inspoly_browser_strict_offline_readiness_20260526.json`

Summary:

- HTML files inspected: 2
- Remote hard boot dependencies: 6
- Remote font dependencies: 2
- Inline `text/babel` script blocks: 2
- Local runtime vendor candidates checked: 3
- Missing local runtime vendor candidates: 3
- Browser desktop static asset serving: not implemented

Hard boot dependencies:

- `https://unpkg.com/react@18/umd/react.development.js` in both browser HTML files
- `https://unpkg.com/react-dom@18/umd/react-dom.development.js` in both browser HTML files
- `https://unpkg.com/@babel/standalone/babel.min.js` in both browser HTML files

Cosmetic or non-boot dependency:

- Google Fonts stylesheet in both browser HTML files. The CSS font stack can fall back to local system fonts, but strict visual parity needs an explicit font policy.

Local asset candidates checked:

- `app/vendor/react.development.js` missing
- `app/vendor/react-dom.development.js` missing
- `app/vendor/babel.min.js` missing

## Strategy Decision

Chosen strategy: keep current online boot behavior and document the asset policy blocker.

Why no patch was made:

- The required local React, ReactDOM, and Babel assets are not present in the repository.
- There is no package lock, local build output, or existing `app/vendor/` asset set to reuse.
- `app/browser_desktop.py` currently serves the root HTML and JSON APIs, but not static vendor asset paths.
- Both browser pages use inline `type="text/babel"` scripts, so removing Babel would require a UI build or transpilation decision.
- Downloading or vendoring runtime assets without product/source/version/license policy would create a release risk.

## What Works Now

The current browser surfaces remain usable in environments where the CDN runtime assets are reachable. Existing analyst labels and current report loading behavior are preserved.

The new strict-offline inventory tool is sidecar-only and read-only:

- `tools/browser_strict_offline_readiness.py`

It can be run to verify the current offline asset state without network access or saved artifact mutation.

## What Does Not Work Offline Yet

Strict offline boot is not ready because:

- React runtime is remote.
- ReactDOM runtime is remote.
- Babel runtime is remote.
- Required local runtime asset files are absent.
- Browser desktop static asset serving for local vendor paths is not implemented.
- Google Fonts remain remote unless product accepts system font fallback or approves local font assets.

## Product Decisions Needed

Before a strict offline patch:

- Approve or provide exact local React, ReactDOM, and Babel asset files.
- Decide dev UMD assets versus production-minified assets.
- Decide whether runtime Babel vendoring is acceptable or whether the browser UI should move to a precompiled build.
- Decide font policy: remote fonts, local fonts, or system font fallback.
- Approve a static asset serving path for `browser_desktop.py` if local assets are used.

## Future Patch Shape

Safe future patch, after asset policy approval:

- Add reviewed local assets under a small static/vendor path.
- Update browser HTML to prefer local assets or use local-only strict offline paths.
- Add static asset serving in the desktop launcher.
- Preserve all current labels, report rendering behavior, sorting, filtering, and old-report compatibility.
- Add static/snapshot tests proving hard remote boot dependencies are gone.

Blocked future patch:

- Rewriting the browser UI from scratch.
- Changing sorting/filtering or analyst semantics.
- Vendoring unpinned or large assets without provenance.
- Introducing a new build pipeline without a separate product/engineering decision.

## Rollback

This campaign made no runtime/browser behavior patch. Rollback is limited to removing the sidecar strict-offline inventory tool, its tests, this report, and the generated compact JSON if the project chooses not to keep this readiness record.

## Verification State

Planned verification for this campaign:

- `py_compile` for the new strict-offline tool and test.
- Strict-offline readiness tests.
- Existing browser offline asset preflight tests.
- Existing browser Side/Outcome label snapshot tests.
- JSON validation for the new readiness output.
- `git diff --check`.
