from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools.generate_unique_review_packets import (
    build_packets_from_rows,
    build_review_packet_payload,
    write_outputs,
)


VALID_WALLET = "0x1234567890abcdef1234567890abcdef12345678"
VALID_TX = "0x" + "a" * 64


class UniqueReviewPacketTests(unittest.TestCase):
    def test_dedupe_produces_unique_packets(self) -> None:
        rows = [
            {
                "dedupeKey": "same",
                "wallet": VALID_WALLET,
                "tradeId": VALID_TX,
                "judgment": "Strong Risk: Retrospective",
                "gateFamily": "retrospective_correctness",
            },
            {
                "dedupeKey": "same",
                "wallet": VALID_WALLET,
                "tradeId": VALID_TX,
                "judgment": "Strong Risk: Retrospective",
                "gateFamily": "retrospective_correctness",
            },
        ]
        packets = build_packets_from_rows(rows)
        self.assertEqual(len(packets), 1)
        self.assertEqual(packets[0]["dedupe_group_size"], 2)

    def test_strong_risk_her_and_overlap_groups_are_separated(self) -> None:
        packets = build_packets_from_rows(
            [
                {"dedupeKey": "strong", "wallet": VALID_WALLET, "judgment": "Strong Risk", "gateFamily": "structural"},
                {"dedupeKey": "her", "wallet": VALID_WALLET, "hardEvidenceSources": ["low_probability_early_winner"]},
                {
                    "dedupeKey": "overlap",
                    "wallet": VALID_WALLET,
                    "judgment": "Strong Risk",
                    "hardEvidenceSources": ["strict_shared_funding_group"],
                },
            ]
        )
        groups = {packet["dedupe_key"]: packet["group"] for packet in packets}
        self.assertEqual(groups["strong"], "strong_risk")
        self.assertEqual(groups["her"], "hard_evidence_review")
        self.assertEqual(groups["overlap"], "overlap")

    def test_missing_optional_fields_do_not_crash(self) -> None:
        packets = build_packets_from_rows([{"judgment": "Strong Risk"}])
        self.assertEqual(len(packets), 1)
        self.assertIn("why_this_may_be_false_positive", packets[0])
        self.assertIn("what_to_inspect_next", packets[0])
        warning_ids = {warning["issue_id"] for warning in packets[0]["critical_field_warnings"]}
        self.assertTrue({"SCHEMA-001", "SCHEMA-002", "SCHEMA-003", "SCHEMA-004", "SCHEMA-005", "SCHEMA-006"}.issubset(warning_ids))

    def test_reporting_schema_warnings_do_not_change_detector_fields(self) -> None:
        row = {
            "dedupeKey": "schema",
            "wallet": VALID_WALLET,
            "judgment": "Strong Risk",
            "score": 88,
            "composition": "structural",
            "gateBranch": "shared_funding_branch",
            "gateType": "structural_gate",
            "marketConditionId": "0xmarket",
            "market": "Example market",
            "tradeId": VALID_TX,
            "fundingEvidenceGrade": "unknown",
            "hardEvidenceSources": [],
            "suppressorConflictReasons": ["near_certainty"],
        }
        packet = build_packets_from_rows([row])[0]
        self.assertEqual(packet["score"], 88)
        self.assertEqual(packet["strong_risk_composition_class"], "structural")
        self.assertEqual(packet["strong_risk_exact_gate_branch"], "shared_funding_branch")
        self.assertEqual(packet["strong_risk_gate_type"], "structural_gate")
        self.assertEqual(packet["condition_id"], "0xmarket")
        self.assertEqual(packet["funding_evidence_grade"], "unknown")
        warning_ids = {warning["issue_id"] for warning in packet["critical_field_warnings"]}
        self.assertEqual(warning_ids, {"SCHEMA-001"})

    def test_suppressor_advisory_is_advisory_only(self) -> None:
        packet = build_packets_from_rows(
            [
                {
                    "dedupeKey": "advisory",
                    "wallet": VALID_WALLET,
                    "judgment": "Strong Risk",
                    "gateType": "structural_gate",
                    "composition": "structural",
                    "gateBranch": "branch",
                    "conditionId": "0xmarket",
                    "suppressors": ["high_volume_public_user"],
                }
            ]
        )[0]
        advisory = {item["pattern"]: item for item in packet["false_positive_advisory"]}
        self.assertIn("high_volume_public_user", advisory)
        self.assertEqual(advisory["high_volume_public_user"]["automatic_action_allowed"], "false")
        self.assertEqual(packet["group"], "strong_risk")

    def test_false_positive_advisory_includes_issue_ids_and_forbidden_use(self) -> None:
        packet = build_packets_from_rows(
            [
                {
                    "dedupeKey": "fp-patterns",
                    "wallet": VALID_WALLET,
                    "market": "Example market",
                    "tradeId": VALID_TX,
                    "conditionId": "0xcondition",
                    "judgment": "Strong Risk",
                    "gateType": "structural_gate",
                    "composition": "structural",
                    "gateBranch": "branch",
                    "suppressors": ["high_volume_public_user", "near_certainty"],
                }
            ]
        )[0]
        advisory = {item["pattern"]: item for item in packet["false_positive_advisory"]}
        self.assertEqual(advisory["no_independent_hard_evidence"]["issue_id"], "FP-001")
        self.assertEqual(advisory["high_volume_public_user"]["issue_id"], "FP-002")
        self.assertEqual(advisory["near_certainty"]["issue_id"], "FP-003")
        self.assertIn("Do not suppress", advisory["near_certainty"]["forbidden_use"])
        self.assertEqual(advisory["high_volume_public_user"]["automatic_action_allowed"], "false")

    def test_funding_unknown_and_stale_advisory_do_not_change_funding_status(self) -> None:
        packet = build_packets_from_rows(
            [
                {
                    "dedupeKey": "fp-funding",
                    "wallet": VALID_WALLET,
                    "market": "Example market",
                    "tradeId": VALID_TX,
                    "conditionId": "0xcondition",
                    "judgment": "Strong Risk",
                    "gateType": "structural_gate",
                    "composition": "structural",
                    "gateBranch": "branch",
                    "fundingEvidenceGrade": "unknown",
                    "suppressors": ["stale_or_resolution_gap", "weak_economic_history"],
                }
            ]
        )[0]
        advisory = {item["pattern"]: item for item in packet["false_positive_advisory"]}
        self.assertEqual(advisory["stale_or_resolution_gap"]["issue_id"], "FP-004")
        self.assertEqual(advisory["weak_economic_history"]["issue_id"], "FP-005")
        self.assertEqual(advisory["funding_unknown"]["issue_id"], "FP-006")
        self.assertEqual(packet["funding_evidence_grade"], "unknown")

    def test_gate_trace_and_retrospective_advisories_are_reporting_only(self) -> None:
        packet = build_packets_from_rows(
            [
                {
                    "dedupeKey": "fp-gate-retro",
                    "wallet": VALID_WALLET,
                    "market": "Example market",
                    "tradeId": VALID_TX,
                    "conditionId": "0xcondition",
                    "judgment": "Strong Risk",
                    "gateType": "structural_gate",
                    "composition": "structural",
                    "gateBranch": "branch",
                    "gateTraceAvailable": False,
                    "retrospectiveOnly": True,
                }
            ]
        )[0]
        advisory = {item["pattern"]: item for item in packet["false_positive_advisory"]}
        self.assertEqual(advisory["gate_trace_missing"]["issue_id"], "FP-007")
        self.assertEqual(advisory["retrospective_only"]["issue_id"], "FP-008")
        self.assertTrue(packet["retrospective_only"])
        self.assertIs(packet["gate_trace_available"], False)

    def test_navigation_aliases_fill_trade_market_wallet_without_scoring_changes(self) -> None:
        wallet = "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd"
        tx_hash = VALID_TX
        packet = build_packets_from_rows(
            [
                {
                    "dedupeKey": "nav",
                    "traderWallet": wallet,
                    "txHash": tx_hash,
                    "marketTitle": "Navigation market",
                    "condition": "0xcondition",
                    "judgment": "Strong Risk",
                    "gateType": "structural_gate",
                    "composition": "structural",
                    "gateBranch": "branch",
                    "score": 77,
                }
            ]
        )[0]
        self.assertEqual(packet["wallet"], wallet)
        self.assertEqual(packet["trade_id"], tx_hash)
        self.assertEqual(packet["market"], "Navigation market")
        self.assertEqual(packet["source_navigation"]["wallet"], wallet)
        self.assertEqual(packet["source_navigation"]["trade_id"], tx_hash)
        self.assertEqual(packet["score"], 77)

    def test_navigation_warnings_for_missing_trade_market_wallet(self) -> None:
        packet = build_packets_from_rows(
            [
                {
                    "dedupeKey": "missing-nav",
                    "judgment": "Strong Risk",
                    "gateType": "structural_gate",
                    "composition": "structural",
                    "gateBranch": "branch",
                    "conditionId": "0xcondition",
                }
            ]
        )[0]
        warning_ids = {warning["issue_id"] for warning in packet["critical_field_warnings"]}
        self.assertTrue({"SCHEMA-007", "SCHEMA-008", "SCHEMA-009"}.issubset(warning_ids))

    def test_clickable_links_only_when_valid_fields_exist(self) -> None:
        rows = [
            {
                "dedupeKey": "valid",
                "wallet": VALID_WALLET,
                "tradeId": VALID_TX,
                "marketUrl": "https://polymarket.com/event/example",
                "judgment": "Strong Risk",
            },
            {
                "dedupeKey": "invalid",
                "wallet": "not-a-wallet",
                "tradeId": "not-a-tx",
                "marketUrl": "not-a-url",
                "judgment": "Strong Risk",
            },
        ]
        packets = {packet["dedupe_key"]: packet for packet in build_packets_from_rows(rows)}
        self.assertIn("polygonscan_wallet", packets["valid"]["links"])
        self.assertIn("polygonscan_transaction", packets["valid"]["links"])
        self.assertIn("polymarket", packets["valid"]["links"])
        self.assertEqual(packets["invalid"]["links"], {})

    def test_false_positive_explanation_fields_exist(self) -> None:
        packets = build_packets_from_rows(
            [
                {
                    "dedupeKey": "fp",
                    "wallet": VALID_WALLET,
                    "judgment": "Strong Risk",
                    "suppressors": ["high_volume_public_user", "domain_specialist"],
                    "fundingEvidenceGrade": "unknown",
                }
            ]
        )
        cautions = packets[0]["why_this_may_be_false_positive"]
        self.assertTrue(any("High-volume" in item for item in cautions))
        self.assertTrue(any("Funding evidence is unknown" in item for item in cautions))

    def test_rows_are_not_modified(self) -> None:
        row = {
            "dedupeKey": "immutable",
            "wallet": VALID_WALLET,
            "judgment": "Strong Risk",
            "score": 91,
            "gateFamily": "structural",
        }
        before = copy.deepcopy(row)
        build_packets_from_rows([row])
        self.assertEqual(row, before)

    def test_legacy_stratified_examples_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "drilldown.json"
            path.write_text(
                json.dumps(
                    {
                        "stratifiedExamples": {
                            "topHardEvidenceReviewWithSuppressors": [
                                {
                                    "wallet": VALID_WALLET,
                                    "hardEvidenceSources": ["low_probability_early_winner"],
                                    "suppressors": ["stale_or_resolution_gap"],
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            payload = build_review_packet_payload([path])
        self.assertEqual(payload["summary"]["unique_packet_count"], 1)
        self.assertEqual(payload["packets"][0]["group"], "hard_evidence_review")

    def test_wallet_groups_summarize_counts_and_suppressors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "diagnostic.json"
            path.write_text(
                json.dumps(
                    {
                        "topManualInspectionRows": [
                            {
                                "dedupeKey": "a",
                                "wallet": VALID_WALLET,
                                "judgment": "Strong Risk",
                                "conditionId": "0xmarket1",
                                "suppressors": ["high_volume_public_user"],
                                "score": 91,
                            },
                            {
                                "dedupeKey": "b",
                                "wallet": VALID_WALLET,
                                "hardEvidenceSources": ["low_probability_early_winner"],
                                "conditionId": "0xmarket2",
                                "suppressors": ["high_volume_public_user", "near_certainty"],
                                "score": 75,
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            payload = build_review_packet_payload([path])
        wallet_group = payload["wallet_groups"][0]
        self.assertEqual(wallet_group["wallet"], VALID_WALLET)
        self.assertEqual(wallet_group["packet_count"], 2)
        self.assertEqual(wallet_group["market_count"], 2)
        self.assertEqual(wallet_group["suppressor_themes"][0]["name"], "high_volume_public_user")

    def test_market_groups_summarize_wallets_without_dropping_packets(self) -> None:
        other_wallet = "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "diagnostic.json"
            path.write_text(
                json.dumps(
                    {
                        "topManualInspectionRows": [
                            {
                                "dedupeKey": "a",
                                "wallet": VALID_WALLET,
                                "judgment": "Strong Risk",
                                "conditionId": "0xmarket1",
                                "market": "Example market",
                            },
                            {
                                "dedupeKey": "b",
                                "wallet": other_wallet,
                                "judgment": "Strong Risk",
                                "conditionId": "0xmarket1",
                                "market": "Example market",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            payload = build_review_packet_payload([path])
        self.assertEqual(payload["summary"]["unique_packet_count"], 2)
        market_group = payload["market_groups"][0]
        self.assertEqual(market_group["packet_count"], 2)
        self.assertEqual(market_group["wallet_count"], 2)
        self.assertIn(VALID_WALLET, market_group["wallets"])

    def test_retrospective_and_source_navigation_summary_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "diagnostic.json"
            path.write_text(
                json.dumps(
                    {
                        "topManualInspectionRows": [
                            {
                                "dedupeKey": "retro",
                                "wallet": VALID_WALLET,
                                "judgment": "Strong Risk",
                                "retrospectiveOnly": True,
                                "sourcePath": "/tmp/source.csv",
                                "sourceRow": 7,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            payload = build_review_packet_payload([path])
        self.assertEqual(payload["retrospective_summary"]["retrospective_only_packets"], 1)
        self.assertEqual(payload["summary"]["source_navigation_packets"], 1)
        self.assertEqual(payload["packets"][0]["source_navigation"]["source_path"], "/tmp/source.csv")

    def test_outputs_are_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "diagnostic.json"
            path.write_text(
                json.dumps(
                    {
                        "topManualInspectionRows": [
                            {
                                "dedupeKey": "out",
                                "wallet": VALID_WALLET,
                                "judgment": "Strong Risk",
                                "sourcePath": "/tmp/source.csv",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            payload = build_review_packet_payload([path])
            outputs = write_outputs(payload, Path(tmp))
            self.assertTrue(Path(outputs["json_path"]).exists())
            self.assertTrue(Path(outputs["markdown_path"]).exists())


if __name__ == "__main__":
    unittest.main()
