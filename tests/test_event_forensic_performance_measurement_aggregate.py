from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.event_forensic_performance_measurement_aggregate import (
    build_measurement_aggregate,
    main,
)


def _summary(
    event_slug: str,
    *,
    markets: int = 1,
    raw_rows: int = 1000,
    candidate_rows: int = 100,
    wallets: int = 50,
    truncated: int = 0,
    seconds: float = 10.0,
    bottleneck: str = "collect_event_trades_seconds",
) -> dict[str, object]:
    return {
        "networkUsed": True,
        "outputDir": f"validation_outputs/{event_slug}",
        "summary": {
            "gateDecision": "performance_measurement_complete",
            "eventSlug": event_slug,
            "marketCount": markets,
            "rawTradeRows": raw_rows,
            "candidateRows": candidate_rows,
            "candidateWalletCount": wallets,
            "truncatedMarketCount": truncated,
            "totalSeconds": seconds,
            "dominantBottleneck": bottleneck,
        },
    }


class EventForensicPerformanceMeasurementAggregateTests(unittest.TestCase):
    def test_single_market_samples_require_subset_for_larger_patch(self) -> None:
        aggregate = build_measurement_aggregate(
            [
                _summary("a", truncated=1, seconds=20),
                _summary("b", seconds=12),
                _summary("c", seconds=1),
            ]
        )

        self.assertEqual(aggregate["summary"]["performanceGate"], "performance_needs_subset_measurement")
        self.assertEqual(aggregate["summary"]["paginationGate"], "pagination_issue_observed")
        self.assertTrue(aggregate["summary"]["subsetApprovalNeeded"])

    def test_multimarket_consistent_bottleneck_supports_patch_rfc(self) -> None:
        aggregate = build_measurement_aggregate(
            [
                _summary("a", markets=2, bottleneck="prefetch_wallet_context_seconds"),
                _summary("b", markets=3, bottleneck="prefetch_wallet_context_seconds"),
            ]
        )

        self.assertEqual(aggregate["summary"]["performanceGate"], "performance_evidence_sufficient_for_patch_rfc")

    def test_cli_writes_aggregate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first.json"
            second = root / "second.json"
            output = root / "aggregate.json"
            first.write_text(json.dumps(_summary("a")), encoding="utf-8")
            second.write_text(json.dumps(_summary("b")), encoding="utf-8")

            self.assertEqual(main([str(first), str(second), "--output", str(output), "--quiet"]), 0)
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(payload["reportType"], "event_forensic_performance_measurement_aggregate")
        self.assertFalse(payload["runtimeBehaviorChanged"])


if __name__ == "__main__":
    unittest.main()
