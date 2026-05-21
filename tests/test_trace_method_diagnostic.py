from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tools.trace_method_diagnostic import (
    classify_diagnostic,
    run_diagnostic,
    write_outputs,
)


def _available_call(method: str, result: object | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "method": method,
        "status": "available",
        "durationSeconds": 0.01,
        "detail": f"{method} ok",
    }
    if result is not None:
        payload["result"] = result
    if isinstance(result, list):
        payload["resultLength"] = len(result)
    return payload


class TraceMethodDiagnosticTests(unittest.TestCase):
    def test_no_endpoint_requires_operator_configuration(self) -> None:
        report = run_diagnostic(urls=[], rpc_caller=lambda *_args: _available_call("unused"))
        self.assertEqual(report["classification"], "operator_rpc_configuration_required")
        self.assertEqual(report["recommended_next_step"], "operator_rpc_configuration_or_capacity_decision")

    def test_available_trace_path_classifies_available(self) -> None:
        def caller(_url: str, method: str, _params: list[object], _timeout: int) -> dict[str, object]:
            if method == "eth_blockNumber":
                return _available_call(method, "0x1000")
            if method == "eth_getLogs":
                return _available_call(method, [])
            return _available_call(method, {"timestamp": "0x1"})

        report = run_diagnostic(
            urls=["https://example.invalid"],
            corpus_path=Path("missing.json"),
            rpc_caller=caller,
        )
        self.assertEqual(report["classification"], "trace_method_path_available")
        self.assertEqual(report["recommended_next_step"], "run_bounded_12_target_validation_smoke")

    def test_default_log_span_uses_configured_runtime_chunk(self) -> None:
        def caller(_url: str, method: str, _params: list[object], _timeout: int) -> dict[str, object]:
            if method == "eth_blockNumber":
                return _available_call(method, "0x1000")
            if method == "eth_getLogs":
                return _available_call(method, [])
            return _available_call(method, {"timestamp": "0x1"})

        with mock.patch.dict(os.environ, {"INSPOLY_POLYGON_RPC_GETLOGS_BLOCK_CHUNK": "321"}):
            report = run_diagnostic(
                urls=["https://example.invalid"],
                corpus_path=Path("missing.json"),
                rpc_caller=caller,
            )

        self.assertEqual(report["configured_getlogs_block_chunk"], 321)
        self.assertEqual(report["log_spans_tested"], [1, 321])

    def test_trace_timeout_classifies_public_rpc_trace_timeout(self) -> None:
        def caller(_url: str, method: str, params: list[object], _timeout: int) -> dict[str, object]:
            if method == "eth_blockNumber":
                return _available_call(method, "0x1000")
            if method == "eth_getLogs":
                request = params[0]
                assert isinstance(request, dict)
                span = int(str(request["toBlock"]), 16) - int(str(request["fromBlock"]), 16) + 1
                if span > 1:
                    return {
                        "method": method,
                        "status": "timeout",
                        "durationSeconds": 8.0,
                        "detail": "synthetic timeout",
                    }
                return _available_call(method, [])
            return _available_call(method, {"timestamp": "0x1"})

        report = run_diagnostic(
            urls=["https://example.invalid"],
            corpus_path=Path("missing.json"),
            rpc_caller=caller,
        )
        self.assertEqual(report["classification"], "public_rpc_trace_timeout")
        self.assertEqual(report["recommended_next_step"], "operator_rpc_configuration_or_capacity_decision")

    def test_endpoint_errors_still_classify_available_path(self) -> None:
        result = classify_diagnostic(
            [
                {
                    "calls": [
                        {"method": "eth_blockNumber", "status": "available"},
                        {"method": "eth_getBlockByNumber", "status": "available"},
                        {"method": "eth_getLogs", "blockSpan": 1, "status": "available"},
                        {"method": "eth_getLogs", "blockSpan": 1500, "status": "network_error"},
                    ]
                },
                {
                    "calls": [
                        {"method": "eth_blockNumber", "status": "available"},
                        {"method": "eth_getBlockByNumber", "status": "available"},
                        {"method": "eth_getLogs", "blockSpan": 1, "status": "available"},
                        {"method": "eth_getLogs", "blockSpan": 1500, "status": "available"},
                    ]
                },
            ],
            configured_endpoint_count=2,
        )
        self.assertEqual(result, "trace_method_path_available_with_endpoint_errors")

    def test_endpoint_errors_recommend_bounded_smoke_with_quarantine(self) -> None:
        def caller(url: str, method: str, params: list[object], _timeout: int) -> dict[str, object]:
            if method == "eth_blockNumber":
                return _available_call(method, "0x1000")
            if method == "eth_getLogs":
                request = params[0]
                assert isinstance(request, dict)
                span = int(str(request["toBlock"]), 16) - int(str(request["fromBlock"]), 16) + 1
                if "bad" in url and span > 1:
                    return {
                        "method": method,
                        "status": "network_error",
                        "durationSeconds": 0.01,
                        "detail": "synthetic endpoint error",
                    }
                return _available_call(method, [])
            return _available_call(method, {"timestamp": "0x1"})

        report = run_diagnostic(
            urls=["https://bad.example", "https://good.example"],
            corpus_path=Path("missing.json"),
            rpc_caller=caller,
        )
        self.assertEqual(report["classification"], "trace_method_path_available_with_endpoint_errors")
        self.assertEqual(
            report["recommended_next_step"],
            "run_bounded_12_target_validation_smoke_with_endpoint_quarantine",
        )

    def test_lightweight_only_when_no_getlogs_calls(self) -> None:
        result = classify_diagnostic(
            [
                {
                    "calls": [
                        {"method": "eth_blockNumber", "status": "available"},
                        {"method": "eth_getBlockByNumber", "status": "available"},
                    ]
                }
            ],
            configured_endpoint_count=1,
        )
        self.assertEqual(result, "public_rpc_lightweight_only")

    def test_writes_json_and_markdown_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            report = {
                "generated_at": "2026-05-05T00:00:00+00:00",
                "classification": "public_rpc_trace_timeout",
                "recommended_next_step": "operator_rpc_configuration_or_capacity_decision",
                "read_only": True,
                "production_model_changes": "none",
                "configured_endpoint_count": 1,
                "endpoint_labels": ["example.invalid"],
                "sample_wallet_source": "synthetic_wallet_no_corpus_sample",
                "sample_wallet_label": "0x0000...dead",
                "log_spans_tested": [1, 1500],
                "per_request_timeout_seconds": 8,
                "total_timeout_seconds": 90,
                "runtime_seconds": 8.0,
                "method_summary": {"eth_getLogs": {"available": 1, "timeout": 1, "rate_limited": 0, "errors": 0}},
                "endpoint_results": [],
                "invariants_preserved": ["_score_trade() unchanged"],
            }
            paths = write_outputs(report, output_dir=output_dir, timestamp="20260505_000000")
            json_path = Path(paths["json_path"])
            markdown_path = Path(paths["markdown_path"])
            self.assertTrue(json_path.exists())
            self.assertTrue(markdown_path.exists())
            self.assertEqual(json.loads(json_path.read_text(encoding="utf-8"))["classification"], "public_rpc_trace_timeout")
            self.assertIn("Trace Method Diagnostic", markdown_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
