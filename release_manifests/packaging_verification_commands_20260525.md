# Packaging Verification Commands - 2026-05-25

Do not run these as a staging script. They are review commands for a human packaging pass.

## Lightweight verification already appropriate for packaging-only changes

```bash
git diff --check
git status --short --ignored
```

## Recommended before any actual commit review

```bash
python3 -m py_compile app/side_outcome.py app/scanner.py app/archive_scanner.py app/event_forensic.py   tools/side_outcome_phase2_impact_audit.py tools/side_outcome_phase4_cluster_direction_audit.py   tools/event_forensic_weak_history_policy_simulation.py tools/event_forensic_weak_history_live_rpc_validation.py   tools/run_known_case_benchmark.py tools/run_inspoly_benchmark_suite.py
python3 -m unittest tests.test_side_outcome_normalization
python3 -m unittest tests.test_side_outcome_phase2_model_contract
python3 -m unittest tests.test_side_outcome_phase4_cluster_direction_audit
python3 -m unittest tests.test_event_forensic_weak_history_review_demotion
python3 -m unittest tests.test_known_case_benchmark
python3 -m unittest tests.test_cross_mode_scoring_contract
python3 -m unittest discover -s tests -p 'test_*.py'
git diff --check
```

## Direct review scans before staging

```bash
rg "capital_at_risk|Phase 3|phase3" app tests tools docs -g '!__pycache__'
rg "threshold|weight|Strong Risk|HER|funding|candidate admission" app/scanner.py app/archive_scanner.py app/event_forensic.py tests
rg "private key|CLOB auth|place order|order placement|trading" app tools tests
```

## Packaging cautions

- `app/event_forensic.py` is the main hunk-split risk: it includes both Side/Outcome Event Forensic semantics and weak-history review-bucket demotion.
- If the reviewer cannot safely hunk-split `app/event_forensic.py`, prefer combining commit 01 and commit 02 into one runtime/policy commit.
- Generated evidence in commit 05 is optional and should remain out of the default commit unless the reviewer wants audit reproducibility inside git.
- `PROJECT_MEMORY.md` remains local working memory by default.
