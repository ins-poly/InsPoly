---
name: strategic-autonomy-review
description: Use this skill when asked to plan next steps, avoid tunnel vision, choose a strategic campaign, prepare a review packet, or act as a strategic implementation lead rather than a local patch agent.
---

# Strategic Autonomy Review Skill

Use this skill for non-trivial, open-ended, architectural, validation, release, performance, or "what next" tasks.

## Required Context

Read, if present:

- `AGENTS.md`
- `PROJECT_MEMORY.md`
- `AI_CONTROL/PROJECT_MEMORY.md`
- `AI_CONTROL/STRATEGIC_OPERATING_SYSTEM.md`
- `AI_CONTROL/STRATEGIC_MAP.md`
- `AI_CONTROL/CURRENT_STATE.md`
- `AI_CONTROL/INVARIANTS_AND_GUARDRAILS.md`
- `AI_CONTROL/DECISION_LOG.md`
- `AI_CONTROL/STRATEGIC_BACKLOG.md`
- `AI_CONTROL/LAST_STRATEGIC_REVIEW.md`

## Procedure

1. Classify the work:
   - local patch
   - strategic campaign
   - diagnostic probe
   - approval-gated proposal
   - release packaging
   - external review packet

2. If not a local patch, produce a Strategic Campaign Brief.

3. Score candidate campaigns using:
   - product leverage
   - risk reduction
   - evidence readiness
   - reversibility
   - dependency unblocking
   - approval load
   - tunnel-vision risk control

4. Recommend the highest-leverage safe campaign.

5. Check guardrails before implementation.

6. Use subagents only when the operator explicitly authorizes subagent work and the current Codex environment supports them:
   - strategy reviewer
   - architecture reviewer
   - regression reviewer
   - validation reviewer

7. Implement only the approved/safe bounded path.

8. Validate.

9. Update strategic state files or propose exact patches.

## Prohibitions

- Do not change product scoring or routing semantics unless explicitly approved.
- Do not turn sidecar helpers into production runtime paths unless explicitly approved.
- Do not broaden pagination completeness, persistence, or schema behavior unless approved.
- Do not stage, commit, push, delete generated artifacts, or mutate saved reports unless explicitly requested.
