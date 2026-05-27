# Last Strategic Review

Date: 2026-05-26 EEST.
Reviewer: Codex local context synthesis, prepared for external GPT review.

## Summary
- The repository has a verified local release candidate: `ad27400 Verify local release candidate state`.
- The full verification matrix passed 1105 tests, and browser strict offline remains `browser_strict_offline_ready`.
- The compact AI_CONTROL layer is now classified as repo process infrastructure, while root `PROJECT_MEMORY.md` and root `AGENTS.md` remain local-only unless the owner decides otherwise.
- The known-case benchmark has been expanded to `known_case_benchmark_v3` with 30 compact offline cases, including false-positive, sidecar-context, and public-source metadata controls.
- The latest committed runtime direction is browser strict-offline readiness via vendored pinned UMD assets.
- The latest committed process direction is local release-candidate verification readiness.
- The biggest strategic risk is no longer missing release evidence; it is either pushing without a staging decision or drifting into another narrow diagnostic loop without a product-level next-step decision.

## Current Strategic Assessment
- The project is strongest when it treats scoring and output routing as conservative analyst-lead generation.
- Most high-risk model changes are currently blocked by explicit gates, which is appropriate.
- Future effort should be selected by product leverage, not by whichever diagnostic tool produced the latest small follow-up.
- The next open-ended Codex run should use the `strategic-autonomy-review` workflow and the ORIENT -> SELECT -> PLAN -> EXECUTE -> VALIDATE -> RECORD cycle before touching code.
- The public-case benchmark expansion has now been completed at the named-user/pattern/market metadata level. Further exact-wallet benchmark work still needs source or local-artifact proof, not runtime/model tuning.
- Good next external review questions are: how to structure known-case benchmark expansion, what cases should be represented as exact-wallet assertions versus pattern-level assertions, and what should remain blocked.

## Recommended Next External GPT Review Focus
- Review whether any candidate source can support exact-wallet assertions without inference.
- Check whether current named-user, market-level, and pattern-level public controls are too broad, too narrow, or missing a key source-quality tier.
- Check whether the guardrails are too broad, too narrow, or missing any strategic stop condition.
- Produce one precise Codex prompt for a bounded known-case benchmark curation campaign.

## Do Not Do From This Review Alone
- Do not change scoring weights, gates, labels, candidate admission, storage, report schemas, pagination completeness, Phase 3 runtime, or sidecar integration.
- Do not stage, commit, push, delete, or clean generated local artifacts.
- Do not start new live/RPC measurements without an explicit operator-selected target and scope.
