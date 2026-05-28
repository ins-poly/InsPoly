# InsPoly RC V4 Validation Matrix - 2026-05-28

## Purpose

This matrix explains what validation protects before the RC V4 draft PR is published.

## Historical RC V4 Validation

The RC V4 completion campaign recorded:

| Check | Recorded result | Protects |
| --- | --- | --- |
| Full unittest discovery | 1240 tests passed | Cross-mode regression surface |
| Compile checks | `app`, `tools`, and `tests` passed | Syntax/import breakage |
| W4/report/browser compatibility | passed | Optional pointer does not break reports or browser loaders |
| Indexer warehouse W0-W4 focused tests | passed | Sidecar warehouse contracts and no-network tools |
| Scoring and known-case benchmark tests | passed | No scoring/gate drift |
| Browser offline and label snapshots | passed | Vendored browser assets and label stability |
| Runtime import scan | passed | Sidecar tools not imported by production paths |
| Copied-metrics scan | passed | No copied warehouse metrics in report payloads |
| `git diff --check` and cached diff check | passed before RC V4 commit | Whitespace and staged diff hygiene |

## Publication Validation To Run

The publication campaign reruns:

- full unittest discovery;
- compile checks over `app`, `tools`, and `tests`;
- JSON validation for new compact summaries;
- documentation path/reference checks;
- Mermaid block sanity checks;
- focused browser/offline/vendor hash and report compatibility tests;
- runtime import scans for sidecar indexer/warehouse tools;
- copied metrics scan;
- Phase 3/scoring/funding gate scan;
- `git diff --check`;
- `git diff --cached --check` after staging.

## Publication Validation Status

Publication matrix result: `passed`.

| Check | Publication result |
| --- | --- |
| Documentation path/reference check | passed |
| New compact JSON validation | passed |
| Mermaid fence sanity | passed |
| Python compile checks | passed for `app`, `tools`, and `tests` |
| Full unittest discovery | 1240 tests passed |
| Focused release suites | 391 tests passed |
| Runtime import scan | passed |
| Pointer copied-metric scan | passed |
| Forbidden publication claim scan | passed |
| `git diff --check` | passed |

The staged diff check is run immediately before the publication documentation commit.
