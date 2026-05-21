from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.strong_risk_gate_diagnostic import build_diagnostic


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _corpus(path: Path, rows_path: Path) -> Path:
    return _write_json(
        path,
        {
            "selected_output_paths": [str(rows_path)],
            "target_results": [
                {
                    "label": "target",
                    "status": "completed_cache_only",
                    "mode": "event_forensic",
                    "tags": ["fresh_rerunnable", "event_forensic", "politics_world", "non_gta"],
                    "audit_paths": [str(rows_path)],
                    "output_paths": [str(rows_path)],
                }
            ],
        },
    )


class StrongRiskGateDiagnosticTests(unittest.TestCase):
    def test_flags_timing_repricing_only_strong_risk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = _write_json(
                root / "rows.json",
                [
                    {
                        "tradeId": "trade",
                        "wallet": "0xabc",
                        "conditionId": "cond",
                        "severity": "Strong Risk",
                        "strongRiskGateTrace": "{}",
                        "strongRiskGateFamily": "timing_repricing",
                        "strongRiskGateName": "timing_led_gate",
                        "strongRiskTimingRepricingOnly": "Yes",
                        "strongRiskHasIndependentHardEvidence": "No",
                        "hardEvidenceSources": "",
                        "openingExposure": "Yes",
                    }
                ],
            )
            summary = build_diagnostic(corpus_path=_corpus(root / "corpus.json", rows))
        self.assertEqual(summary["strongRiskByTimingRepricingOnly"]["true"], 1)
        self.assertEqual(summary["potentialGateLeakageCandidateRows"], 1)

    def test_flags_suppressor_conflict_without_independent_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = _write_json(
                root / "rows.json",
                [
                    {
                        "tradeId": "trade",
                        "wallet": "0xabc",
                        "conditionId": "cond",
                        "severity": "Strong Risk",
                        "strongRiskGateTrace": "{}",
                        "strongRiskGateFamily": "timing_repricing",
                        "strongRiskSuppressorConflict": "Yes",
                        "strongRiskSuppressorConflictReasons": "high_volume_public_user",
                        "reasonsAgainst": "high_volume_public_user",
                        "strongRiskHasIndependentHardEvidence": "No",
                        "hardEvidenceSources": "",
                        "openingExposure": "Yes",
                    }
                ],
            )
            summary = build_diagnostic(corpus_path=_corpus(root / "corpus.json", rows))
        self.assertEqual(summary["strongRiskBySuppressorConflict"]["true"], 1)
        self.assertEqual(summary["potentialGateLeakageCandidateRows"], 1)

    def test_missing_gate_trace_is_saved_field_insufficiency(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = _write_json(
                root / "rows.json",
                [
                    {"id": "legacy-1", "severity": "Strong Risk"},
                    {"id": "legacy-2", "severity": "Strong Risk"},
                ],
            )
            summary = build_diagnostic(corpus_path=_corpus(root / "corpus.json", rows))
        self.assertEqual(summary["strongRiskRowsWithoutGateTrace"], 2)
        self.assertEqual(summary["recommendation"], "saved_fields_insufficient_rerun_with_trace_needed")

    def test_clear_independent_structural_evidence_is_not_leakage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = _write_json(
                root / "rows.json",
                [
                    {
                        "tradeId": "trade",
                        "wallet": "0xabc",
                        "conditionId": "cond",
                        "severity": "Strong Risk",
                        "strongRiskGateTrace": "{}",
                        "strongRiskGateFamily": "structural",
                        "strongRiskGateName": "structure_led_gate",
                        "strongRiskHasIndependentHardEvidence": "Yes",
                        "strongRiskIndependentEvidenceSources": "split_wallet_pattern",
                        "hardEvidenceSources": "split_wallet_pattern",
                        "openingExposure": "Yes",
                    }
                ],
            )
            summary = build_diagnostic(corpus_path=_corpus(root / "corpus.json", rows))
        self.assertEqual(summary["potentialGateLeakageCandidateRows"], 0)
        self.assertEqual(summary["recommendation"], "no_gate_change_needed_source_attribution_clear")


if __name__ == "__main__":
    unittest.main()
