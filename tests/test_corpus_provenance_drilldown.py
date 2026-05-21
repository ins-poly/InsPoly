from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.corpus_provenance_drilldown import build_drilldown, render_markdown


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _target(
    label: str,
    path: Path,
    *,
    tags: list[str] | None = None,
    status: str = "completed_cache_only",
) -> dict:
    return {
        "label": label,
        "mode": "event_forensic",
        "status": status,
        "tags": tags
        or ["fresh_rerunnable", "event_forensic", "politics_world", "non_gta"],
        "audit_paths": [str(path)],
        "output_paths": [str(path)],
        "validationRunMode": "cache_only" if status == "completed_cache_only" else "network",
    }


class CorpusProvenanceDrilldownTests(unittest.TestCase):
    def test_reads_latest_corpus_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = _write_json(root / "rows.json", [{"id": "row", "severity": "Low Risk"}])
            corpus = _write_json(
                root / "corpus.json",
                {
                    "final_classification": "post-v2 behavior acceptable on cache-only corpus",
                    "selected_output_paths": [str(rows)],
                    "target_results": [_target("target", rows)],
                },
            )
            acceptance = _write_json(root / "acceptance.json", {"classification": "accepted"})
            recall = _write_json(root / "recall.json", {"classification": "no recall opportunity observed"})
            consistency = _write_json(root / "consistency.json", {"classification": "consistent"})
            rpc = _write_json(root / "rpc.json", {"classification": "public RPC insufficient for full network corpus"})

            summary = build_drilldown(
                corpus_path=corpus,
                acceptance_path=acceptance,
                recall_path=recall,
                consistency_path=consistency,
                public_rpc_limit_path=rpc,
            )

        self.assertEqual(summary["artifact_classifications"]["acceptance"], "accepted")
        self.assertEqual(summary["artifact_classifications"]["recall"], "no recall opportunity observed")
        self.assertEqual(summary["rowsLoadedFromSavedOutputs"], 1)

    def test_handles_missing_referenced_outputs_gracefully(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing = root / "missing.json"
            corpus = _write_json(
                root / "corpus.json",
                {"selected_output_paths": [str(missing)], "target_results": [_target("missing", missing)]},
            )
            summary = build_drilldown(corpus_path=corpus)
        self.assertEqual(summary["rowsLoadedFromSavedOutputs"], 0)
        self.assertEqual(len(summary["missingReferencedOutputPaths"]), 1)

    def test_reports_strong_risk_rows_with_no_hard_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = _write_json(
                root / "rows.json",
                [
                    {
                        "id": "sr-no-hard",
                        "severity": "Strong Risk",
                        "score": 82,
                        "openingExposureFlag": True,
                        "strongRiskExactGateBranch": "timing_led_gate",
                        "strongRiskGateEvidenceSources": ["rapid_favorable_repricing"],
                        "strongRiskTimingProofSources": ["rapid_favorable_repricing"],
                    }
                ],
            )
            corpus = _write_json(root / "corpus.json", {"selected_output_paths": [str(rows)], "target_results": [_target("t", rows)]})
            summary = build_drilldown(corpus_path=corpus)
        self.assertEqual(summary["strongRisk"]["totalStrongRiskRows"], 1)
        self.assertEqual(summary["strongRisk"]["strongRiskRowsWithNoHardEvidenceSources"], 1)

    def test_deduplication_key_collapses_duplicate_strong_risk_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            row = {
                "tradeId": "trade-1",
                "wallet": "0xabc",
                "conditionId": "cond",
                "severity": "Strong Risk",
                "strongRiskGateFamily": "timing_repricing",
                "strongRiskGateName": "timing_led_gate",
            }
            rows = _write_json(root / "rows.json", [dict(row), dict(row)])
            corpus = _write_json(root / "corpus.json", {"selected_output_paths": [str(rows)], "target_results": [_target("t", rows)]})
            summary = build_drilldown(corpus_path=corpus)
        self.assertEqual(summary["strongRisk"]["totalStrongRiskRows"], 2)
        self.assertEqual(summary["strongRisk"]["uniqueStrongRiskRows"], 1)
        self.assertGreater(summary["strongRisk"]["strongRiskDuplication"]["strongRiskDuplicationRatio"], 1)

    def test_deduplication_keeps_distinct_trades_from_same_wallet_market(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = _write_json(
                root / "rows.json",
                [
                    {
                        "tradeId": "trade-1",
                        "wallet": "0xabc",
                        "conditionId": "cond",
                        "severity": "Strong Risk",
                    },
                    {
                        "tradeId": "trade-2",
                        "wallet": "0xabc",
                        "conditionId": "cond",
                        "severity": "Strong Risk",
                    },
                ],
            )
            corpus = _write_json(root / "corpus.json", {"selected_output_paths": [str(rows)], "target_results": [_target("t", rows)]})
            summary = build_drilldown(corpus_path=corpus)
        self.assertEqual(summary["strongRisk"]["uniqueStrongRiskRows"], 2)

    def test_reports_strong_risk_by_gate_family(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = _write_json(
                root / "rows.json",
                [
                    {
                        "id": "timing",
                        "severity": "Strong Risk",
                        "strongRiskGateFamily": "timing_repricing",
                        "strongRiskGateName": "timing_led_gate",
                    }
                ],
            )
            corpus = _write_json(root / "corpus.json", {"selected_output_paths": [str(rows)], "target_results": [_target("t", rows)]})
            summary = build_drilldown(corpus_path=corpus)
        self.assertEqual(summary["strongRisk"]["strongRiskRowsByGateFamily"]["timing_repricing"], 1)

    def test_reports_her_source_distribution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = _write_json(
                root / "rows.json",
                [
                    {
                        "id": "her",
                        "severity": "Low Risk",
                        "hardEvidenceReviewTier": "Hard Evidence Review",
                        "hardEvidenceSources": ["dormant_wallet_reactivation"],
                        "hardEvidenceStrength": "Strong",
                        "openingExposureFlag": True,
                    }
                ],
            )
            corpus = _write_json(root / "corpus.json", {"selected_output_paths": [str(rows)], "target_results": [_target("t", rows)]})
            summary = build_drilldown(corpus_path=corpus)
        self.assertEqual(summary["hardEvidenceReview"]["totalHardEvidenceReviewRows"], 1)
        self.assertEqual(
            summary["hardEvidenceReview"]["hardEvidenceReviewRowsByHardEvidenceSources"]["dormant_wallet_reactivation"],
            1,
        )

    def test_flags_cex_bridge_proxy_only_her(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = _write_json(
                root / "rows.json",
                [
                    {
                        "id": "proxy-her",
                        "hardEvidenceReviewTier": "Hard Evidence Review",
                        "hardEvidenceSources": ["suspicious_recent_funding"],
                        "fundingEvidenceGrade": "cex_proxy",
                        "suspiciousFundingQuality": "strong",
                    }
                ],
            )
            corpus = _write_json(root / "corpus.json", {"selected_output_paths": [str(rows)], "target_results": [_target("t", rows)]})
            summary = build_drilldown(corpus_path=corpus)
        self.assertEqual(
            summary["hardEvidenceReview"]["hardInvalidConditionCounts"]["cex_bridge_proxy_only_hard_evidence_review"],
            1,
        )

    def test_flags_multi_hop_unknown_her_without_support(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = _write_json(
                root / "rows.json",
                [
                    {
                        "id": "multi-hop",
                        "hardEvidenceReviewTier": "Hard Evidence Review",
                        "hardEvidenceSources": ["suspicious_recent_funding"],
                        "fundingEvidenceGrade": "multi_hop_unknown",
                        "suspiciousFundingQuality": "strong",
                        "suspiciousFundingIndependentSupport": False,
                    }
                ],
            )
            corpus = _write_json(root / "corpus.json", {"selected_output_paths": [str(rows)], "target_results": [_target("t", rows)]})
            summary = build_drilldown(corpus_path=corpus)
        self.assertEqual(summary["hardEvidenceReview"]["multiHopUnknownHardEvidenceReviewRowsWithoutIndependentSupport"], 1)
        self.assertEqual(
            summary["hardEvidenceReview"]["hardInvalidConditionCounts"]["multi_hop_unknown_hard_evidence_without_independent_support"],
            1,
        )

    def test_flags_suspicious_funding_only_her_with_suppressors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = _write_json(
                root / "rows.json",
                [
                    {
                        "id": "suppressed-funding",
                        "hardEvidenceReviewTier": "Hard Evidence Review",
                        "hardEvidenceSources": ["suspicious_recent_funding"],
                        "fundingEvidenceGrade": "suspicious_direct",
                        "suspiciousFundingQuality": "strong",
                        "suspiciousFundingIndependentSupport": False,
                        "reasonsAgainst": ["high_volume_public_user"],
                    }
                ],
            )
            corpus = _write_json(root / "corpus.json", {"selected_output_paths": [str(rows)], "target_results": [_target("t", rows)]})
            summary = build_drilldown(corpus_path=corpus)
        self.assertEqual(
            summary["hardEvidenceReview"]["hardInvalidConditionCounts"][
                "suspicious_funding_only_hard_evidence_review_with_suppressors"
            ],
            1,
        )

    def test_detects_one_family_dominance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dominant = _write_json(
                root / "dominant.json",
                [{"id": f"sr-{i}", "severity": "Strong Risk", "score": 80 + i} for i in range(5)],
            )
            other = _write_json(root / "other.json", [{"id": "other", "severity": "Low Risk"}])
            targets = [
                _target("dominant", dominant, tags=["fresh_rerunnable", "event_forensic", "politics_world", "non_gta"]),
                _target("other", other, tags=["fresh_rerunnable", "archive", "sports_crypto", "non_gta"]),
            ]
            for i in range(6):
                targets.append(
                    {
                        "label": f"empty-{i}",
                        "mode": "event_forensic",
                        "status": "completed_cache_only",
                        "tags": ["fresh_rerunnable", "event_forensic", "resolved_or_partial", "non_gta"],
                        "audit_paths": [],
                        "output_paths": [],
                    }
                )
            corpus = _write_json(
                root / "corpus.json",
                {"selected_output_paths": [str(dominant), str(other)], "target_results": targets},
            )
            summary = build_drilldown(corpus_path=corpus)
        self.assertEqual(summary["targetFamilyAndCacheInterpretation"]["classification"], "one_family_dominates")

    def test_handles_cache_only_corpus_classification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = _write_json(root / "rows.json", [{"id": "row", "severity": "Low Risk"}])
            targets = [
                _target("target", rows, tags=["fresh_rerunnable", "event_forensic", "politics_world", "non_gta"]),
                _target("archive", rows, tags=["fresh_rerunnable", "archive", "sports_crypto", "non_gta"]),
            ]
            for i in range(6):
                targets.append(
                    {
                        "label": f"empty-{i}",
                        "mode": "event_forensic",
                        "status": "completed_cache_only",
                        "tags": ["fresh_rerunnable", "event_forensic", "resolved_or_partial", "non_gta"],
                        "audit_paths": [],
                        "output_paths": [],
                    }
                )
            corpus = _write_json(
                root / "corpus.json",
                {
                    "final_classification": "post-v2 behavior acceptable on cache-only corpus",
                    "selected_output_paths": [str(rows)],
                    "target_results": targets,
                },
            )
            summary = build_drilldown(corpus_path=corpus)
        self.assertEqual(summary["targetFamilyAndCacheInterpretation"]["classification"], "cache_only_limits_model_interpretation")

    def test_legacy_rows_with_missing_fields_are_insufficient_not_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = _write_json(root / "rows.json", [{"id": "legacy", "severity": "Strong Risk"}])
            corpus = _write_json(root / "corpus.json", {"selected_output_paths": [str(rows)], "target_results": [_target("legacy", rows)]})
            summary = build_drilldown(corpus_path=corpus)
            markdown = render_markdown(summary)
        self.assertEqual(summary["strongRisk"]["diagnosticClassification"], "strong_risk_saved_fields_insufficient")
        self.assertIn("Corpus Provenance Drilldown", markdown)


if __name__ == "__main__":
    unittest.main()
