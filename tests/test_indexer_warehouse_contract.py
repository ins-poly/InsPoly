from __future__ import annotations

from unittest.mock import patch
import unittest

from app.indexer.warehouse_contract import (
    EXPECTED_WAREHOUSE_TABLES,
    collection_metadata_status,
    cursor_contract_status,
    evaluate_warehouse_w0_contract,
    raw_json_policy_status,
    retention_policy_status,
    table_contract_status,
)


class IndexerWarehouseContractTests(unittest.TestCase):
    def test_expected_table_contract_reports_complete_schema(self) -> None:
        status = table_contract_status(
            {
                "status": "complete",
                "expectedTables": list(EXPECTED_WAREHOUSE_TABLES),
                "presentTables": list(EXPECTED_WAREHOUSE_TABLES),
                "missingTables": [],
            }
        )

        self.assertTrue(status["ready"])
        self.assertEqual(status["status"], "complete")
        self.assertEqual(status["missingTables"], [])

    def test_missing_table_contract_reports_blocking_reason(self) -> None:
        status = table_contract_status(
            {
                "status": "missing_tables",
                "expectedTables": list(EXPECTED_WAREHOUSE_TABLES),
                "presentTables": ["indexed_markets"],
                "missingTables": ["indexed_trades"],
            }
        )

        self.assertFalse(status["ready"])
        self.assertEqual(status["status"], "missing_expected_tables")
        self.assertIn("missing_table:indexed_trades", status["blockingReasons"])

    def test_cursor_contract_classifies_aggregate_cursor_warning(self) -> None:
        status = cursor_contract_status(
            [
                {
                    "source": "bounded_live_sidecar",
                    "cursorKey": "markets",
                    "status": "ok",
                    "lastError": "",
                    "isStale": False,
                },
                {
                    "source": "bounded_live_sidecar",
                    "cursorKey": "public_trades",
                    "status": "ok",
                    "lastError": "",
                    "isStale": False,
                },
            ]
        )

        self.assertTrue(status["ready"])
        self.assertEqual(status["status"], "ready_with_warnings")
        self.assertIn("aggregate_public_trade_cursor_only", status["warnings"])

    def test_cursor_contract_blocks_missing_or_error_cursors(self) -> None:
        missing = cursor_contract_status([])
        errored = cursor_contract_status(
            [
                {
                    "source": "bounded_live_sidecar",
                    "cursorKey": "public_trades",
                    "status": "error",
                    "lastError": "provider failed",
                    "isStale": False,
                }
            ]
        )

        self.assertFalse(missing["ready"])
        self.assertIn("missing_indexer_cursors", missing["blockingReasons"])
        self.assertFalse(errored["ready"])
        self.assertEqual(errored["status"], "cursor_errors")

    def test_malformed_raw_json_policy_blocks_w0(self) -> None:
        status = raw_json_policy_status({"malformedRawJsonCount": 2})

        self.assertFalse(status["ready"])
        self.assertEqual(status["status"], "blocked_malformed_raw_json")

    def test_per_target_collection_metadata_is_ready_when_summary_has_rows_by_target(self) -> None:
        status = collection_metadata_status(
            {
                "summary": {
                    "publicTradeCollection": {
                        "collectionPolicy": "per_target_public_trade_cap",
                        "rowsByTarget": {"market-a": 60, "market-b": 60},
                        "perTargetPublicTradeLimit": 60,
                        "aggregatePublicTradeLimit": 180,
                    }
                }
            }
        )

        self.assertTrue(status["ready"])
        self.assertEqual(status["status"], "per_target_metadata_ready")
        self.assertEqual(status["rowsByTarget"], {"market-a": 60, "market-b": 60})

    def test_missing_collection_metadata_is_external_summary_requirement_not_schema_blocker(self) -> None:
        status = collection_metadata_status(None)

        self.assertTrue(status["ready"])
        self.assertEqual(status["status"], "external_summary_required")
        self.assertIn("collection_metadata_not_stored_in_sidecar_db", status["warnings"])

    def test_local_only_retention_policy_prefers_sidecar_root(self) -> None:
        ready = retention_policy_status(".inspoly_indexer/warehouse_w0/indexer.sqlite3")
        warning = retention_policy_status("/tmp/indexer.sqlite3")
        blocked = retention_policy_status("https://example.test/indexer.sqlite3")

        self.assertTrue(ready["ready"])
        self.assertEqual(ready["status"], "local_sidecar_path_ready")
        self.assertTrue(warning["ready"])
        self.assertEqual(warning["status"], "local_path_requires_operator_retention_policy")
        self.assertFalse(blocked["ready"])
        self.assertEqual(blocked["status"], "blocked_external_or_service_path")

    def test_old_db_compatibility_is_limited_but_readable_without_collection_summary(self) -> None:
        report = _readiness_report()

        status = evaluate_warehouse_w0_contract(report)

        self.assertTrue(status["warehouseW0Ready"])
        self.assertEqual(status["collectionMetadataStatus"]["status"], "external_summary_required")
        self.assertEqual(status["oldDbCompatibility"]["status"], "sidecar_readable_w0_limited")
        self.assertFalse(status["oldDbCompatibility"]["requiresMigration"])

    def test_contract_helper_is_pure_no_network_no_runtime(self) -> None:
        report = _readiness_report()

        with patch("socket.create_connection", side_effect=AssertionError("network call blocked")):
            with patch("urllib.request.urlopen", side_effect=AssertionError("network call blocked")):
                status = evaluate_warehouse_w0_contract(report)

        self.assertFalse(status["runtimeBoundaries"]["networkUsed"])
        self.assertFalse(status["runtimeBoundaries"]["productionIntegration"])
        self.assertFalse(status["runtimeBoundaries"]["warehouseWriterImplemented"])


def _readiness_report() -> dict[str, object]:
    return {
        "dbPath": ".inspoly_indexer/example/indexer.sqlite3",
        "schema": {
            "status": "complete",
            "expectedTables": list(EXPECTED_WAREHOUSE_TABLES),
            "presentTables": list(EXPECTED_WAREHOUSE_TABLES),
            "missingTables": [],
        },
        "summary": {
            "malformedRawJsonCount": 0,
            "duplicateIndicatorCount": 0,
        },
        "cursorHealth": [
            {
                "source": "bounded_live_sidecar",
                "cursorKey": "markets",
                "cursorValue": "done",
                "status": "ok",
                "lastError": "",
                "isStale": False,
            },
            {
                "source": "bounded_live_sidecar",
                "cursorKey": "public_trades",
                "cursorValue": "conditions:3:rows:180",
                "status": "ok",
                "lastError": "",
                "isStale": False,
            },
        ],
    }


if __name__ == "__main__":
    unittest.main()
