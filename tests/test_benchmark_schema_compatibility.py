from __future__ import annotations

import csv
import tempfile
from pathlib import Path
import unittest

from app.benchmark_cases import load_benchmark_case, validate_benchmark_case
from tools import benchmark_label_schema as schema
from tools.benchmark_label_completion_status import build_status
from tools.benchmark_label_csv_preflight import build_preflight
from tools.benchmark_label_cycle import build_cycle
from tools.benchmark_label_expectation_report import build_expectation_report
from tools.benchmark_label_readiness_gate import build_readiness


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "benchmark_cases"
CASE_FIELDS = list(schema.CASE_LEVEL_REQUIRED_FIELDS)


def _case_row(
    case_id: str,
    *,
    label: str = "",
    confidence: str = "",
    notes: str = "",
    detector: str = "",
    fresh: str = "",
) -> dict[str, str]:
    row = {field: "" for field in CASE_FIELDS}
    row.update(
        {
            "benchmarkCaseId": case_id,
            "sourceArtifact": "event_forensic_outputs/example/event_analysis.json",
            "queueRank": "1",
            "eventSlug": "example-event",
            "marketSlug": "example-market",
            "conditionId": f"cond-{case_id}",
            "marketQuestion": "Example market?",
            "wallet": "0xabc",
            "tradeId": f"trade-{case_id}",
            "strongRiskFlag": "yes",
            "hardEvidenceReviewFlag": "no",
            "fundingEvidenceGrade": "unknown",
            "falsePositiveAdvisoryMatches": "funding_unknown",
            "missingCriticalFields": "fundingEvidenceGrade",
            "whySuspiciousSummary": "Saved suspicious structure.",
            "whyMaybeFalsePositiveSummary": "Funding/source limits remain.",
            "whatToInspectNext": "Review source artifact.",
            "expectedAnalystDisposition": label,
            "humanLabelConfidence": confidence,
            "expectedDetectorDisposition": detector,
            "freshValidationRequired": fresh,
            "notes": notes,
        }
    )
    return row


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class BenchmarkSchemaCompatibilityTests(unittest.TestCase):
    def test_schema_detection_legacy_local_case(self) -> None:
        detected = schema.detect_schema(["localCaseId", "expectedAnalystDisposition", "humanLabelConfidence"])
        self.assertEqual(detected["schemaType"], schema.SCHEMA_LEGACY_LOCAL_CASE)
        self.assertEqual(detected["idField"], "localCaseId")

    def test_schema_detection_case_level_benchmark(self) -> None:
        detected = schema.detect_schema(CASE_FIELDS)
        self.assertEqual(detected["schemaType"], schema.SCHEMA_CASE_LEVEL_BENCHMARK)
        self.assertEqual(detected["idField"], "benchmarkCaseId")

    def test_unknown_schema_fails_with_missing_column_diagnostics(self) -> None:
        detected = schema.detect_schema(["case", "label"])
        self.assertEqual(detected["schemaType"], schema.SCHEMA_UNKNOWN_OR_INVALID)
        self.assertIn("localCaseId or benchmarkCaseId", detected["missingRequiredColumns"])

    def test_case_level_blank_template_is_structurally_valid_unlabeled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            labels = Path(tmp) / "case_blank.csv"
            _write_csv(labels, CASE_FIELDS, [_case_row("CASE-1")])
            payload = build_preflight(template_csv_path=labels, labels_csv_path=labels)
        self.assertEqual(payload["summary"]["schemaType"], schema.SCHEMA_CASE_LEVEL_BENCHMARK)
        self.assertEqual(payload["summary"]["preflightStatus"], "structure_ok_unlabeled")
        self.assertEqual(payload["summary"]["usableLabelRows"], 0)
        self.assertEqual(payload["summary"]["draftAssistedLabelRows"], 0)

    def test_case_level_draft_assisted_rows_are_structurally_valid_not_usable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            labels = Path(tmp) / "case_draft.csv"
            _write_csv(
                labels,
                CASE_FIELDS,
                [
                    _case_row(
                        "CASE-1",
                        label="likely_false_positive",
                        confidence="medium",
                        detector="reporting_only_note",
                        fresh="yes",
                        notes="DRAFT_ASSISTED_NOT_FINAL: requires human review before final benchmark use.",
                    )
                ],
            )
            preflight = build_preflight(template_csv_path=labels, labels_csv_path=labels)
            readiness = build_readiness({}, labels_csv_path=labels, min_usable_labels=1)
            expectation = build_expectation_report(
                {},
                labels_csv_path=labels,
                preflight_payload=preflight,
                readiness_payload=readiness,
            )
        self.assertEqual(preflight["summary"]["preflightStatus"], "structure_ok_draft_assisted_only")
        self.assertEqual(preflight["summary"]["usableLabelRows"], 0)
        self.assertEqual(preflight["summary"]["draftAssistedLabelRows"], 1)
        self.assertFalse(preflight["summary"]["draftAssistedLabelsCountedUsable"])
        self.assertEqual(readiness["summary"]["readinessStatus"], "draft_assisted_only_not_human_valid")
        self.assertEqual(readiness["summary"]["usableLabeledRows"], 0)
        self.assertEqual(expectation["summary"]["expectationStatus"], "draft_assisted_only_not_human_evidence")
        self.assertEqual(expectation["summary"]["usableLabeledRows"], 0)

    def test_case_level_manual_label_without_draft_marker_can_be_usable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            labels = Path(tmp) / "case_human.csv"
            _write_csv(
                labels,
                CASE_FIELDS,
                [
                    _case_row(
                        "CASE-1",
                        label="plausible_insider_style",
                        confidence="high",
                        detector="rfc_only_review_candidate",
                        fresh="no",
                        notes="Human finalized after source review.",
                    )
                ],
            )
            preflight = build_preflight(template_csv_path=labels, labels_csv_path=labels)
            readiness = build_readiness({}, labels_csv_path=labels, min_usable_labels=1)
        self.assertEqual(preflight["summary"]["preflightStatus"], "structure_ok_human_labeled")
        self.assertEqual(preflight["summary"]["usableLabelRows"], 1)
        self.assertEqual(readiness["summary"]["readinessStatus"], "ready_for_reporting_regression_only")
        self.assertEqual(readiness["summary"]["usableLabeledRows"], 1)
        self.assertTrue(readiness["summary"]["assumesManualFinalizationForNonDraftRows"])

    def test_allowed_values_enforced_for_case_level_and_legacy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case_labels = root / "case_invalid.csv"
            _write_csv(
                case_labels,
                CASE_FIELDS,
                [_case_row("CASE-1", label="bad_value", confidence="high", fresh="maybe")],
            )
            case_payload = build_preflight(template_csv_path=case_labels, labels_csv_path=case_labels)
            legacy_template = root / "legacy_template.csv"
            legacy_labels = root / "legacy_labels.csv"
            legacy_header = (
                "localCaseId,sourceType,eventSlug,market,conditionId,wallet,"
                "expectedAnalystDisposition,humanLabelConfidence,freshValidationRequired\n"
            )
            legacy_template.write_text(
                legacy_header + "LOCAL-1,packet,event,Market,cond,0xabc,,,yes\n",
                encoding="utf-8",
            )
            legacy_labels.write_text(
                legacy_header + "LOCAL-1,packet,event,Market,cond,0xabc,bad_value,high,maybe\n",
                encoding="utf-8",
            )
            legacy_payload = build_preflight(template_csv_path=legacy_template, labels_csv_path=legacy_labels)
        self.assertEqual(case_payload["summary"]["preflightStatus"], "structure_or_values_need_fix")
        self.assertEqual(case_payload["summary"]["invalidLabelRows"], 1)
        self.assertEqual(legacy_payload["summary"]["preflightStatus"], "structure_or_values_need_fix")
        self.assertEqual(legacy_payload["summary"]["invalidLabelRows"], 1)

    def test_legacy_workflow_remains_ready_for_readiness_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.csv"
            labels = root / "labels.csv"
            rows = [
                f"LOCAL-{idx},unique_review_packet,event,Market {idx},cond-{idx},0xabc,likely_false_positive,high,yes"
                for idx in range(12)
            ]
            template_rows = [
                f"LOCAL-{idx},unique_review_packet,event,Market {idx},cond-{idx},0xabc,,,yes"
                for idx in range(12)
            ]
            header = (
                "localCaseId,sourceType,eventSlug,market,conditionId,wallet,"
                "expectedAnalystDisposition,humanLabelConfidence,freshValidationRequired\n"
            )
            template.write_text(header + "\n".join(template_rows) + "\n", encoding="utf-8")
            labels.write_text(header + "\n".join(rows) + "\n", encoding="utf-8")
            payload = build_preflight(template_csv_path=template, labels_csv_path=labels)
        self.assertEqual(payload["summary"]["schemaType"], schema.SCHEMA_LEGACY_LOCAL_CASE)
        self.assertEqual(payload["summary"]["preflightStatus"], "ready_for_readiness_gate")
        self.assertEqual(payload["summary"]["usableLabelRows"], 12)

    def test_completion_status_does_not_count_draft_assisted_as_usable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft = root / "benchmark_case_level_draft_labels_20260506.csv"
            _write_csv(
                draft,
                CASE_FIELDS,
                [
                    _case_row(
                        "CASE-1",
                        label="likely_false_positive",
                        confidence="medium",
                        fresh="yes",
                        notes="DRAFT_ASSISTED_NOT_FINAL: dry run only.",
                    )
                ],
            )
            payload = build_status(input_dir=root, labels_csv_path=draft)
        self.assertEqual(payload["summary"]["selectedSchemaType"], schema.SCHEMA_CASE_LEVEL_BENCHMARK)
        self.assertEqual(payload["summary"]["selectedCompletionStatus"], "draft_assisted_only")
        self.assertEqual(payload["summary"]["selectedUsableLabelRows"], 0)
        self.assertEqual(payload["summary"]["selectedDraftAssistedLabelRows"], 1)

    def test_cycle_preserves_case_schema_and_draft_only_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft = root / "benchmark_case_level_draft_labels_20260506.csv"
            _write_csv(
                draft,
                CASE_FIELDS,
                [
                    _case_row(
                        "CASE-1",
                        label="likely_false_positive",
                        confidence="medium",
                        detector="reporting_only_note",
                        fresh="yes",
                        notes="DRAFT_ASSISTED_NOT_FINAL: dry run only.",
                    )
                ],
            )
            payload = build_cycle(input_dir=root, output_dir=root, labels_csv_path=draft, min_usable_labels=1)
        self.assertEqual(payload["summary"]["schemaType"], schema.SCHEMA_CASE_LEVEL_BENCHMARK)
        self.assertEqual(payload["summary"]["cycleStatus"], "draft_assisted_only_not_human_valid")
        self.assertEqual(payload["summary"]["preflightStatus"], "structure_ok_draft_assisted_only")
        self.assertEqual(payload["summary"]["usableLabeledRows"], 0)
        self.assertEqual(payload["summary"]["draftAssistedLabelRows"], 1)
        self.assertFalse(payload["summary"]["draftAssistedLabelsCountedUsable"])

    def test_schema_validates_minimal_known_case(self) -> None:
        case = load_benchmark_case(FIXTURES / "minimal_known_case.json")

        self.assertEqual(case.case_id, "known-low-odds-shadow-001")
        self.assertEqual(case.expected["shadow_metric"], "shadow_low_odds_position_size")
        self.assertEqual(case.observed["status"], "not_run")
        self.assertEqual(case.artifact_refs[0].mutable, False)

    def test_schema_rejects_production_action_fields(self) -> None:
        with self.assertRaisesRegex(ValueError, "production-action"):
            load_benchmark_case(FIXTURES / "ambiguous_production_action.json")

    def test_expected_and_observed_are_separate_objects(self) -> None:
        with self.assertRaisesRegex(ValueError, "observed must be an object"):
            validate_benchmark_case(
                {
                    "case_id": "bad-observed",
                    "title": "Bad observed",
                    "expected": {"shadow_metric": "shadow_low_odds_position_size"},
                    "observed": "not-run",
                }
            )

    def test_benchmark_helper_is_not_imported_by_runtime_paths(self) -> None:
        for relative_path in (
            "app/scanner.py",
            "app/archive_scanner.py",
            "app/event_forensic.py",
            "app/polymarket.py",
            "app/storage.py",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("benchmark_cases", source)


if __name__ == "__main__":
    unittest.main()
