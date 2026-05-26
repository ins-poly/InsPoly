# Strategic Review Packet Template V2

Use this when preparing a packet for external GPT or for a future Codex session that needs compact strategic context.

## Required Sections

1. Project purpose.
2. Product north star.
3. Current architecture summary.
4. Current state and gate decisions.
5. Latest changed files grouped by function.
6. What changed in the latest cycle.
7. Why those changes were made.
8. Tests/validation run and results.
9. What was not validated.
10. Known unresolved issues.
11. Strategic risks and tunnel-vision risks.
12. Current strategic portfolio options.
13. Candidate next campaigns with scores.
14. Recommended next campaign and why.
15. Approval-gated items.
16. Exact guardrail excerpts constraining next steps.
17. Precise prompt back to Codex.

## Candidate Campaign Scoring

Use 0-5 scores:

| Candidate | Product leverage | Risk reduction | Evidence readiness | Reversibility | Dependency unblocking | Approval load | Tunnel-vision risk control | Total | Notes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| A |  |  |  |  |  |  |  |  |  |

`Approval load`: 5 means safe/no approval needed. 0 means heavily approval-gated.
`Tunnel-vision risk control`: 5 means low risk of overfitting to local details.

## Prompt To External GPT

```text
You are the strategic architecture reviewer for this coding project.

You do not have access to the full repository unless I paste additional files. Use only this packet unless I provide more context.

Your task:
1. Identify whether Codex is overfitting to local bugs instead of strategic architecture.
2. Check whether the recommended campaign aligns with the project purpose, current state, and guardrails.
3. Identify hidden risks, missing validation, architectural drift, and unnecessary complexity.
4. Re-rank the next 1-3 strategic campaigns.
5. Separate safe implementation tasks from approval-gated tasks.
6. Write one precise prompt I can paste back into Codex.
7. Do not recommend changing product scoring, gates, visibility, schema, persistence, or external dependencies unless the packet explicitly says the operator approved that area.

Here is the packet:
[PASTE PACKET]
```

## Prompt Back To Codex

```text
Before implementing anything, read AGENTS.md, PROJECT_MEMORY.md, AI_CONTROL/PROJECT_MEMORY.md, AI_CONTROL/STRATEGIC_OPERATING_SYSTEM.md, AI_CONTROL/STRATEGIC_MAP.md, AI_CONTROL/CURRENT_STATE.md, AI_CONTROL/INVARIANTS_AND_GUARDRAILS.md, AI_CONTROL/DECISION_LOG.md, AI_CONTROL/STRATEGIC_BACKLOG.md, AI_CONTROL/LAST_STRATEGIC_REVIEW.md, and the relevant source/test/docs files.

Use the external GPT recommendations as advisory input only. Reconcile them against current code, root memory, and repository guardrails.

First produce a Strategic Campaign Brief:
1. Current understanding of the project state.
2. Strategic objective of the task.
3. Candidate paths considered.
4. Recommended path and rationale.
5. Modules/files likely affected.
6. Invariants that must not be touched.
7. Approval gates.
8. Smallest safe implementation path.
9. Risks of local overfitting or tunnel vision.
10. Tests/validation commands to run.
11. Whether operator approval is required before implementation.

Do not edit code until this brief is written.
```
