import json
import tempfile
import unittest
from pathlib import Path

from tools.public_case_evidence_bridge import build_public_case_evidence_bridge, main as bridge_main


ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests/fixtures/known_case_benchmark/post_side_outcome_known_cases.json"


class PublicCaseEvidenceBridgeTests(unittest.TestCase):
    def test_bridge_summarizes_non_exact_public_tiers(self) -> None:
        report = build_public_case_evidence_bridge(CORPUS, root=ROOT)
        summary = report["summary"]

        self.assertEqual(report["gateDecision"], "public_case_evidence_bridge_no_safe_upgrade")
        self.assertEqual(summary["publicCaseCount"], 6)
        self.assertEqual(summary["exactWalletSupportedCount"], 0)
        self.assertEqual(summary["namedUserLocalWalletCandidateCount"], 0)
        self.assertEqual(summary["namedUserOnlyCount"], 2)
        self.assertEqual(summary["patternLevelOnlyCount"], 2)
        self.assertEqual(summary["marketLevelOnlyCount"], 2)
        self.assertEqual(summary["publicSourceUrlCount"], 9)
        self.assertEqual(summary["localArtifactRefsThatProveWalletIdentity"], 0)

    def test_bridge_keeps_local_artifact_refs_advisory(self) -> None:
        report = build_public_case_evidence_bridge(CORPUS, root=ROOT)
        case_results = report["caseResults"]
        refs = [
            ref
            for case in case_results
            for ref in case["localArtifactRefs"]
        ]

        self.assertGreater(len(refs), 0)
        self.assertTrue(all(ref["pathExists"] is False for ref in refs))
        self.assertTrue(all(ref["proves_wallet_identity"] is False for ref in refs))
        self.assertTrue(all(case["exactWalletDetectionAllowed"] is False for case in case_results))

    def test_bridge_cli_writes_compact_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "bridge.json"
            self.assertEqual(
                bridge_main(["--corpus", str(CORPUS), "--root", str(ROOT), "--output", str(output), "--quiet"]),
                0,
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(payload["reportType"], "public_case_exact_wallet_evidence_bridge")
        self.assertEqual(payload["summary"]["publicCaseCount"], 6)
        self.assertFalse(payload["networkUsed"])
        self.assertFalse(payload["runtimeBehaviorChanged"])


if __name__ == "__main__":
    unittest.main()
