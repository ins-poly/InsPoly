import json
import tempfile
import unittest
from pathlib import Path

from tools.public_case_label_intake_validator import (
    main as validator_main,
    validate_intake_payload,
)


def _valid_exact_label() -> dict[str, object]:
    return {
        "accepted_for_benchmark": True,
        "benchmark_case_id": "known-public_maduro_enforcement_named_user_control",
        "condition_id": "0x" + "a" * 64,
        "confidence": "fixture_grade",
        "curator": "human-reviewer",
        "evidence_quote_short": "Source explicitly links the named account to this wallet.",
        "evidence_summary": "Official source and local artifact link the named user to wallet 0x1111111111111111111111111111111111111111 on the market.",
        "evidence_timestamp": "2026-05-27",
        "forbidden_interpretation": "Do not generalize this accepted label to other public cases or scoring changes.",
        "label_id": "label-maduro-exact-001",
        "limitations": "Applies only to the cited wallet, user, and market.",
        "local_artifact_refs": [
            {
                "match": "source identity linked to wallet",
                "path": "validation_outputs/example.json",
                "proves_wallet_identity": True,
            }
        ],
        "market_slug": "maduro-out-by-january-31-2026",
        "polymarket_username": "named-user",
        "proposed_assertion_level": "exact_wallet_supported",
        "review_status": "accepted",
        "source_titles": ["Fixture-grade source"],
        "source_urls": ["https://example.com/source"],
        "wallet_address": "0x1111111111111111111111111111111111111111",
    }


class PublicCaseLabelIntakeValidatorTests(unittest.TestCase):
    def test_valid_exact_label_requires_fixture_grade_identity(self) -> None:
        payload = {
            "schema_version": "public_case_label_intake_v1",
            "sidecar_only": True,
            "labels": [_valid_exact_label()],
        }

        self.assertEqual(validate_intake_payload(payload), [])

    def test_exact_wallet_label_rejects_missing_wallet_and_market(self) -> None:
        label = _valid_exact_label()
        label["wallet_address"] = ""
        label["market_slug"] = ""
        label["condition_id"] = ""
        payload = {
            "schema_version": "public_case_label_intake_v1",
            "sidecar_only": True,
            "labels": [label],
        }

        errors = validate_intake_payload(payload)

        self.assertTrue(any("requires a full 0x wallet_address" in error for error in errors))
        self.assertTrue(any("requires market_slug or condition_id" in error for error in errors))

    def test_pattern_level_label_rejects_exact_wallet_claim(self) -> None:
        label = _valid_exact_label()
        label["label_id"] = "pattern-overclaim"
        label["proposed_assertion_level"] = "pattern_level_only"
        label["accepted_for_benchmark"] = False
        label["review_status"] = "deferred"
        payload = {
            "schema_version": "public_case_label_intake_v1",
            "sidecar_only": True,
            "labels": [label],
        }

        errors = validate_intake_payload(payload)

        self.assertTrue(any("pattern_level_only must not include wallet_address" in error for error in errors))

    def test_local_wallet_candidate_cannot_be_accepted_as_exact_truth(self) -> None:
        label = _valid_exact_label()
        label["label_id"] = "local-candidate"
        label["proposed_assertion_level"] = "named_user_local_wallet_candidate"
        payload = {
            "schema_version": "public_case_label_intake_v1",
            "sidecar_only": True,
            "labels": [label],
        }

        errors = validate_intake_payload(payload)

        self.assertTrue(any("cannot be accepted as benchmark exact-wallet truth" in error for error in errors))

    def test_cli_writes_validation_report_without_applying_labels(self) -> None:
        payload = {
            "schema_version": "public_case_label_intake_v1",
            "sidecar_only": True,
            "labels": [_valid_exact_label()],
        }
        with tempfile.TemporaryDirectory() as tmp:
            intake = Path(tmp) / "intake.json"
            output = Path(tmp) / "report.json"
            intake.write_text(json.dumps(payload), encoding="utf-8")

            self.assertEqual(
                validator_main([str(intake), "--output", str(output), "--quiet"]),
                0,
            )
            report = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(report["gateDecision"], "public_case_label_intake_valid")
        self.assertFalse(report["labelsApplied"])
        self.assertFalse(report["runtimeBehaviorChanged"])


if __name__ == "__main__":
    unittest.main()
