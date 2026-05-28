# Strategic Operating System

Purpose: force Codex to act as a strategic implementation lead, not only as a local patching agent.

This file governs non-trivial work in this repository. It complements, but does not replace:

- `AGENTS.md`
- root `PROJECT_MEMORY.md`
- `AI_CONTROL/PROJECT_MEMORY.md`
- `AI_CONTROL/STRATEGIC_MAP.md`
- `AI_CONTROL/CURRENT_STATE.md`
- `AI_CONTROL/INVARIANTS_AND_GUARDRAILS.md`
- `AI_CONTROL/DECISION_LOG.md`
- `AI_CONTROL/STRATEGIC_BACKLOG.md`

When these sources conflict, use this precedence:

1. Direct operator instruction in the current task.
2. Safety/security constraints.
3. Current code and tests.
4. Root `PROJECT_MEMORY.md`.
5. `AI_CONTROL/INVARIANTS_AND_GUARDRAILS.md`.
6. `AI_CONTROL/DECISION_LOG.md`.
7. `AI_CONTROL/CURRENT_STATE.md`.
8. `AI_CONTROL/STRATEGIC_MAP.md`.
9. `AI_CONTROL/STRATEGIC_BACKLOG.md`.
10. This file.

## Core strategic mandate
Every non-trivial task must advance one of these product-level objectives:

1. Increase analyst reliability.
2. Reduce false-positive or overclaiming risk.
3. Improve validation and evidence quality.
4. Improve performance only where measured bottlenecks justify it.
5. Improve offline/local workflow usability.
6. Prepare safe release/review packaging.
7. Clarify blocked decisions through RFCs, probes, or review packets.

Do not optimize for more flags, more complexity, broader scope, or cleaner architecture unless it directly supports one of the objectives above.

## Mandatory Cycle: ORIENT -> SELECT -> PLAN -> EXECUTE -> VALIDATE -> RECORD

### 1. ORIENT
Before implementing, answer:

- What is the user actually trying to improve?
- What is the current repo state?
- Which strategic files constrain this task?
- Which runtime files and tests are relevant?
- What is already solved?
- What is blocked?
- What is fragile?

### 2. SELECT
For open-ended or strategic tasks, select one bounded campaign from the strategic portfolio.

Use this process scoring model. This is a planning tool only; it must never affect product scoring logic.

Score each candidate from 0 to 5:

- Product leverage: does this improve analyst reliability, validation, usability, or release readiness?
- Risk reduction: does it reduce false positives, drift, regression, or ambiguity?
- Evidence readiness: is there enough current evidence to act safely?
- Reversibility: can the work be reverted or kept sidecar/RFC-only?
- Dependency unblocking: does it unlock later high-value work?
- Approval load: 5 means no operator approval required; 0 means heavily approval-gated.
- Tunnel-vision risk: 5 means low risk of local overfitting; 0 means high risk.

Recommend the candidate with the best combination of leverage, safety, and evidence readiness. Do not choose a campaign merely because it is the most recent problem encountered.

### 3. PLAN
Produce a Strategic Campaign Brief:

1. Campaign name.
2. Strategic objective.
3. Current state.
4. Candidate paths considered.
5. Recommended path and rationale.
6. Files/modules likely affected.
7. Invariants and approval gates.
8. Validation plan.
9. Stop conditions.
10. Expected state updates.

### 4. EXECUTE
During execution:

- Prefer additive, reversible changes.
- Keep sidecar/probe/RFC work separate from runtime changes.
- Do not broaden scoring, visibility, inclusion, pagination completeness, or persistence behavior without explicit approval.
- If you discover a new approval gate, stop and revise the plan.
- If implementation becomes broader than planned, stop and write a Tunnel-Vision Check.

### 5. VALIDATE
Validation must match the touched risk surface.

Minimum baseline for runtime Python changes:

- `python3 -m py_compile app/*.py tools/*.py tests/*.py`
- `python3 -m unittest discover -s tests -p 'test_*.py'`

For markdown/process-only changes, explain why runtime tests are not required.

For strategic probes, preserve raw evidence and explicitly state what was not proven.

### 6. RECORD
At the end of meaningful work, update or propose updates to:

- `AI_CONTROL/CURRENT_STATE.md`
- `AI_CONTROL/DECISION_LOG.md`
- `AI_CONTROL/STRATEGIC_BACKLOG.md`
- `AI_CONTROL/LAST_STRATEGIC_REVIEW.md`
- `AI_CONTROL/STRATEGIC_REVIEW_PACKET.md`, when external GPT review is useful.

Do not record claims that were not validated.

## Strategic Portfolio

Maintain active awareness of these campaign categories:

### A. Release readiness
Goal: safely package existing progress for review or PR.

Good when:
- Code is stable.
- Main risk is staging, verification, or packaging.
- Operator asks to publish/share/push.

Default output:
- Release plan.
- Files to include/exclude.
- Verification matrix.
- No staging/push unless approved.

### B. Known-case benchmark curation
Goal: improve validation against known investigative cases and false-positive examples.

Good when:
- Scoring drift or confidence calibration is a concern.
- More runtime changes would be speculative.
- Public cases or curated fixtures are available.

Default output:
- Benchmark schema additions.
- Source notes.
- False-positive notes.
- Tests/audits without changing scoring gates.

### C. Bounded performance/pagination evidence
Goal: identify measured bottlenecks or provider completeness issues without changing production semantics.

Good when:
- Large Event Forensic runs are slow or incomplete.
- There is a selected target market/event.
- Provider/API behavior needs proof.

Default output:
- Probe tool or packet.
- Measurements.
- No production pagination expansion unless approved.

### D. Analyst UX and report clarity
Goal: make existing evidence easier to interpret without changing scoring semantics.

Good when:
- Outputs are technically correct but hard to interpret.
- The analyst needs better summaries, labels, or review queues.

Default output:
- Additive report fields or UI copy, if schema-safe.
- Legacy compatibility tests.
- No semantic changes to routing or ranking.

### E. RFC-only blocked systems
Goal: clarify approval-gated work without implementing it.

Good when:
- Work touches scoring, gates, storage schema, runtime Phase 3, pagination expansion, replay persistence, dependencies, or external live behavior.

Default output:
- RFC with options, risks, rollback plan, tests, and operator decision points.

## Tunnel-Vision Check

Trigger this check if:

- You patched the same area twice without resolving the strategic objective.
- A diagnostic produces another diagnostic instead of a decision.
- You are optimizing performance without measured bottleneck proof.
- A sidecar helper starts looking like runtime integration.
- You are tempted to change protected semantics to make a test pass.
- A broad refactor appears attractive.

Template:

```markdown
## Tunnel-Vision Check

Strategic objective:
Current local issue:
Is this issue actually blocking the objective?
What evidence supports continuing?
What safer bounded alternative exists?
What should move to backlog instead?
Do I need operator approval?
Decision: continue / stop / ask operator / convert to RFC / convert to probe
```

## End-Of-Response Format

For non-trivial work, end with:

- What changed.
- What was validated.
- What was not validated.
- Strategic state updates made or proposed.
- Recommended next campaign.
- Any operator decisions needed.
