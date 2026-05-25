from __future__ import annotations

from pathlib import Path
import csv
import shutil
import tempfile
import unittest

from tools.validate_polymarket_ledger_against_artifacts import (
    STATUS_OK,
    STATUS_UNKNOWN,
    STATUS_WARNING,
    audit_artifact_dir,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "polymarket_ledger_artifacts"


class PolymarketLedgerArtifactAuditTests(unittest.TestCase):
    def test_profile_like_fixture_matches_summary_and_current_positions(self) -> None:
        audit = audit_artifact_dir(FIXTURES / "profile_like_good")

        self.assertEqual(audit.status, STATUS_WARNING)
        self.assertEqual(audit.rows_loaded, 4)
        self.assertEqual(audit.position_count, 3)
        self.assertTrue(all(check.status == STATUS_OK for check in audit.checks))
        self.assertEqual(self._check(audit, "summary:total_buy_api_cash").actual, "46.5")
        self.assertEqual(self._check(audit, "summary:remaining_yes_shares").actual, "85")

    def test_multi_market_wallet_positions_are_not_collapsed(self) -> None:
        audit = audit_artifact_dir(FIXTURES / "profile_like_good")

        condition_tokens = {
            (position.condition_id, position.token_id, position.outcome)
            for position in audit.positions
        }
        self.assertEqual(
            condition_tokens,
            {
                ("cond-a", "yes-a", "Yes"),
                ("cond-b", "yes-b", "Yes"),
                ("cond-b", "no-b", "No"),
            },
        )

    def test_activity_usdc_size_is_preferred_over_size_times_price(self) -> None:
        audit = audit_artifact_dir(FIXTURES / "profile_like_good")
        yes_a = next(position for position in audit.positions if position.token_id == "yes-a")

        self.assertEqual(yes_a.total_buy_cash, "41")
        self.assertEqual(self._check(audit, "summary:total_buy_api_cash").actual, "46.5")
        self.assertTrue(
            any(note["note"] == "source_cash_disagreement" for note in audit.quality_notes)
        )

    def test_missing_cash_is_unknown_not_zero(self) -> None:
        audit = audit_artifact_dir(FIXTURES / "missing_cash_unknown")

        self.assertEqual(audit.status, STATUS_WARNING)
        buy_cash = self._check(audit, "summary:total_buy_api_cash")
        self.assertEqual(buy_cash.status, STATUS_UNKNOWN)
        self.assertIsNone(buy_cash.actual)
        self.assertIn("not coerced to zero", buy_cash.details)
        self.assertTrue(any(note["note"] == "unknown_cash_source" for note in audit.quality_notes))

    def test_source_cash_disagreement_explains_summary_cash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "artifact"
            shutil.copytree(FIXTURES / "profile_like_good", target)
            self._rewrite_summary_metric(target / "summary_calculations.csv", "total_buy_api_cash", "45.50")

            audit = audit_artifact_dir(target)

        check = self._check(audit, "summary:total_buy_api_cash")
        self.assertEqual(check.status, STATUS_WARNING)
        self.assertIn("source_cash_disagreement", check.details)

    def _check(self, audit, name: str):
        for check in audit.checks:
            if check.name == name:
                return check
        raise AssertionError(f"Missing audit check: {name}")

    def _rewrite_summary_metric(self, path: Path, metric: str, value: str) -> None:
        rows = []
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            fieldnames = reader.fieldnames or ["metric", "value", "notes"]
            for row in reader:
                if row.get("metric") == metric:
                    row["value"] = value
                rows.append(row)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)


if __name__ == "__main__":
    unittest.main()
