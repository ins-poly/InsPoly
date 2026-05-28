# Browser Offline Asset Policy RFC

Date: 2026-05-26

RFC gate: `browser_offline_asset_policy_ready_for_product_decision`

Current strict-offline gate: `browser_offline_blocked_requires_asset_policy`

Implementation in this campaign: `false`

## Context

The strict-offline readiness audit found that both browser UIs still depend on remote runtime assets:

- React from `https://unpkg.com/react@18/umd/react.development.js`
- ReactDOM from `https://unpkg.com/react-dom@18/umd/react-dom.development.js`
- Babel standalone from `https://unpkg.com/@babel/standalone/babel.min.js`
- Google Fonts stylesheets

The repository currently has no `package.json`, lockfile, frontend build config, local JS vendor assets, local font assets, or static vendor serving path in `app/browser_desktop.py`.

## Recommendation

Recommended strategy after explicit product/engineering approval:

`vendor_pinned_umd_assets_with_static_serving_first`

This means:

- vendor exact pinned UMD assets for React, ReactDOM, and Babel standalone;
- add a small provenance manifest with source URL, package name, exact version, license, SHA-256, and byte size for every vendored asset;
- add a narrow static asset serving path to `app/browser_desktop.py`;
- update both browser HTML files to load the local assets;
- preserve all current UI labels, report rendering, old-report fallback, sorting, filtering, and analyst semantics;
- keep runtime Babel for the first strict-offline patch to avoid a broad UI rewrite;
- make font handling a separate explicit choice: system fallback by default, local fonts only if approved.

This strategy is the smallest path to strict offline boot because it preserves the current inline `type="text/babel"` UI implementation. Removing runtime Babel should be a later build-pipeline campaign, not the first offline asset patch.

## Strategy Evaluation

| Strategy | Decision | Reason |
|---|---|---|
| A. Vendor pinned UMD React/ReactDOM/Babel plus font policy | recommended after approval | Closest to current browser shape; avoids UI rewrite; testable with static asset checks. Needs source/license/provenance approval and static serving patch. |
| B. Vendor React/ReactDOM only, keep Babel remote/fallback | rejected for strict offline | Inline `text/babel` requires Babel at runtime, so strict offline boot would still fail. |
| C. Remove runtime Babel by precompiling browser scripts | defer | This could reduce runtime dependencies, but requires extracting/transpiling large inline scripts and proving UI equivalence. Existing repo has no build pipeline. |
| D. Introduce minimal build pipeline | defer | Reproducible long-term path, but it adds package/lock/build maintenance and changes release workflow. It should not be introduced just to solve the immediate offline blocker. |
| E. Keep browser online-capable only | acceptable until approval | Current analyst delivery is usable when CDN assets are reachable. It remains the safe default until offline asset policy is approved. |

## Required Asset Policy

Before vendoring any browser runtime asset, the implementation must record:

- package name;
- exact version, not a floating major range;
- source URL used to obtain the asset;
- license name and source license file path or URL;
- SHA-256 hash;
- byte size;
- vendoring date;
- reviewer/operator who approved the asset;
- whether a source map is intentionally excluded or included.

Recommended local layout:

- `app/vendor/browser/manifest.json`
- `app/vendor/browser/react/<version>/react.development.js` or approved production equivalent
- `app/vendor/browser/react-dom/<version>/react-dom.development.js` or approved production equivalent
- `app/vendor/browser/babel-standalone/<version>/babel.min.js`
- optional approved font assets under `app/vendor/browser/fonts/`

The future implementation should not use floating CDN aliases such as `@18` in local provenance. It should pin the exact artifact version and hash at the time of vendoring.

## Browser Desktop Serving Contract

Future local static serving should be narrow:

- serve only files under the approved vendor directory;
- reject path traversal;
- use a small content-type map for `.js`, `.css`, `.woff`, `.woff2`, `.ttf`, and `.json`;
- keep existing `/`, `/api/bootstrap`, `/api/run`, `/api/case-detail`, `/api/scan`, `/api/stop`, `/api/open-output`, and `/api/open-exports-dir` behavior unchanged;
- do not expose reports, private paths, config files, environment variables, or arbitrary filesystem reads.

## HTML Reference Contract

Future HTML patch should:

- replace hard remote boot scripts with local vendor paths;
- remove or gate Google Fonts according to the approved font policy;
- preserve script order: React, ReactDOM, Babel, then inline browser app script;
- preserve all current labels and UI behavior;
- keep remote fallback only if product explicitly accepts non-strict offline mode. For strict offline release, no hard boot script may require network.

## Remote Fallback Decision

Two modes are possible:

- strict offline mode: local assets only; remote fallback is not used for boot.
- online-compatible mode: local assets preferred, remote fallback allowed when product accepts network dependency.

This RFC recommends strict offline mode for a future release patch, because the current blocker is explicitly offline boot.

## Fonts

Recommended default: remove hard reliance on Google Fonts for strict offline and accept existing CSS font-family fallbacks unless product requires visual parity.

If visual parity is required, font files need the same provenance manifest discipline as runtime JS assets.

## Build Pipeline Decision

No build pipeline should be introduced in the first offline patch. The repo currently has no frontend package manifest, lockfile, build config, or local build output. Introducing a build pipeline is a larger release workflow change and should require a separate RFC.

A later build-pipeline RFC may be worthwhile if the team wants to remove runtime Babel and move the inline React app into compiled browser assets.

## Tests Required Before Implementation

Future implementation must add or update checks proving:

- strict-offline readiness reports `browser_strict_offline_ready`;
- no remote hard boot dependencies remain in either browser HTML file;
- all local vendor references exist and are served by the desktop launcher;
- browser Side/Outcome labels remain unchanged;
- Event Forensic scope and weak-history labels remain unchanged if the Event Forensic UI HTML is touched;
- old-report loading remains absent-safe;
- no UI sorting/filtering behavior changes;
- no model/scoring/gate/storage changes.

## Rollback

Rollback for a future implementation should be straightforward:

- restore previous HTML remote script references;
- remove the narrow static asset serving path;
- leave the provenance manifest and readiness report as historical evidence unless cleanup is explicitly approved.

No current rollback is needed because this campaign is RFC-only.

## Product Decision Required

Implementation is blocked until the owner approves:

- exact React, ReactDOM, and Babel standalone asset versions and source URLs;
- license/provenance recording format;
- strict offline local-only mode versus local-preferred remote fallback mode;
- system font fallback versus local font vendoring;
- static vendor serving under `browser_desktop.py`;
- whether runtime Babel is acceptable for the first offline patch.

## Decision

Current decision: `browser_offline_asset_policy_ready_for_product_decision`.

No runtime/browser implementation should happen until the product/engineering decision above is explicit.
