# InsPoly Next Backlog After Side/Outcome Reform

- Date: 2026-05-22
- Scope: next-action plan only
- Runtime implementation in this step: false
- Network/RPC used: false

## 1. Safe Local Tasks

### 1.1 Curate a labeled known-case benchmark corpus

- Why it matters: current replay has strong drift counts but weak analyst labels.
- Likely files affected: `tests/fixtures/benchmark_cases/`, `app/benchmark_cases.py`, `tests/test_benchmark_schema_compatibility.py`, docs under `docs/`.
- Regression risk: low if fixtures remain sidecar-only.
- Allowed scope: static fixtures and tests only; no scorer behavior changes.
- Stop conditions: if labels require live web research, private source judgment, or production action fields.
- Status 2026-05-22: completed as a sidecar-only Side/Outcome known-case corpus at `tests/fixtures/known_case_benchmark/post_side_outcome_known_cases.json`. Gate: `known_case_corpus_ready`. The corpus has 16 cases, covers all required BUY/SELL YES/NO, Phase 2, Phase 4, malformed, old-report, sensitive-overlap, Phase 3 blocked, scanner/archive/Event Forensic categories, and remains insufficient for the remembered live Event Forensic weak-history near-certainty ranking risk.

### 1.2 Extend post-side/outcome replay with stable saved-output packets

- Why it matters: remembered fragile Event Forensic cases need stable before/after evidence.
- Likely files affected: `tools/post_side_outcome_benchmark_replay.py`, `tests/test_post_side_outcome_benchmark_replay.py`, `validation_outputs/`.
- Regression risk: low for sidecar-only work.
- Allowed scope: local artifacts only, no RPC.
- Stop conditions: if required reports are missing locally or need live data.
- Status 2026-05-22: still relevant, but narrower after the known-case corpus. Next safe local version should add only stable saved-output packets for the remembered Event Forensic weak-history case if such reports exist locally; otherwise this becomes the RPC/operator-approved task below.

### 1.3 Archive visibility drift monitoring

- Why it matters: archive rows remain mixed and old/lossy rows can be misread.
- Likely files affected: `tools/archive_visibility_doc_drift_audit.py`, archive-focused tests, docs.
- Regression risk: low if read-only.
- Allowed scope: sidecar audit/docs/tests only.
- Stop conditions: any proposal to hide/exclude cases or change archive visibility behavior.

### 1.4 Browser label compatibility snapshots

- Why it matters: Token price vs Economic prob copy is a key analyst-facing contract.
- Likely files affected: browser static tests and docs.
- Regression risk: low.
- Allowed scope: tests/docs only.
- Stop conditions: any sort/filter behavior change or UI redesign.

## 2. Tasks Requiring RPC / Operator Approval

### 2.1 Weak-history near-certainty Event Forensic rerun

- Why it matters: PROJECT_MEMORY still records a ranking risk for wallets with weak economic history and near-certain winning trades.
- Likely files affected: new validation output directory and docs; no runtime files unless a bug is proven later.
- Regression risk: medium if results are used to justify scorer changes.
- Allowed scope after approval: bounded live rerun or loading stable saved outputs; compare ranking before/after Side/Outcome semantics.
- Stop conditions: if rerun requires scorer tuning, Phase 3, direct gates, storage, UI sorting, or broad live indexing.
- Status 2026-05-22: remains the top approval-gated step. The known-case corpus now covers the local semantic contracts, but does not close this live/saved-distribution validation blocker.

### 2.2 Whole-event vs single-market replay

- Why it matters: Side/Outcome does not resolve scope ambiguity.
- Likely files affected: validation outputs, docs, possibly tests if stable saved artifacts exist.
- Regression risk: medium for analyst interpretation.
- Allowed scope after approval: replay/report comparison only.
- Stop conditions: any runtime broadening of single-market scope.

### 2.3 Large-event performance replay

- Why it matters: whole-event forensic remains expensive on large completed events.
- Likely files affected: validation outputs, performance docs.
- Regression risk: low if measurement-only, higher if optimization begins.
- Allowed scope after approval: measurement only.
- Stop conditions: any candidate filtering, scoring, or network pacing change without a separate task.

## 3. Tasks Requiring User Product Decision

### 3.1 Commit/staging policy for broad reform worktree

- Why it matters: Side/Outcome files are mixed with donor/shadow/indexer sidecar work.
- Likely files affected: git staging only, no source edits.
- Regression risk: operational/review risk, not runtime risk.
- Allowed scope: choose consolidated commit vs split commits.
- Stop conditions: no commit/push without explicit approval.

### 3.2 Whether audit JSON/review packets belong in git

- Why it matters: generated evidence improves reproducibility but adds noise and timestamped churn.
- Likely files affected: `side_outcome_audits/`, `side_outcome_review_packets/`, `.gitignore`.
- Regression risk: low runtime, medium repository hygiene.
- Allowed scope: staging/ignore policy only.
- Stop conditions: if outputs include private/local-only context that should not be published.

### 3.3 UI sorting/filtering changes

- Why it matters: current labels are clearer, but sort remains raw-token entry price by design.
- Likely files affected: `app/browser_ui.html`, `app/browser_event_forensic_ui.html`, browser tests.
- Regression risk: medium to high for analyst workflows.
- Allowed scope only after approval: copy/filter/sort behavior RFC and tests.
- Stop conditions: any silent sort/filter behavior change.

## 4. Tasks That Should Remain Blocked

### 4.1 Phase 3 capital-at-risk runtime normalization

- Block reason: audit gate remains `keep_phase3_blocked`; SELL max-loss semantics need accounting guardrails.
- Files likely affected if ever approved: `app/scanner.py`, `app/archive_scanner.py`, `app/event_forensic.py`, `app/side_outcome.py`, tests.
- Stop conditions: missing side/outcome/price/size, old notional-only rows, funding/HER sensitivity, or need for weight/threshold tuning.

### 4.2 Scoring weights and thresholds

- Block reason: Phase 2/4 changed semantics without retuning. Any tuning needs a labeled benchmark.
- Stop conditions: no human-labeled corpus or no explicit approval.

### 4.3 Direct Strong Risk/HER/funding/candidate-admission migration

- Block reason: current overlap is indirect and expected; direct gate migration is higher risk.
- Stop conditions: any proposal to change gate criteria without RFC, tests, and approval.

### 4.4 Storage schema, live indexer, or trading behavior

- Block reason: outside Side/Outcome reform and explicitly prohibited in current campaign.
- Stop conditions: any required Postgres/Redis/Graph Node, CLOB auth, private keys, order placement, or automatic startup.
