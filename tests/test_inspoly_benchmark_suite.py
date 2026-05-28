from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.run_inspoly_benchmark_suite import (
    REQUIRED_CATEGORIES,
    run_benchmark_suite,
    main,
    validate_registry,
)


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "tests" / "fixtures" / "inspoly_benchmark_registry" / "registry.json"


class InsPolyBenchmarkSuiteTests(unittest.TestCase):
    def test_registry_schema_and_required_categories(self) -> None:
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        errors = validate_registry(registry)

        self.assertEqual(errors, [])
        categories = {item["category"] for item in registry["items"]}
        self.assertEqual(REQUIRED_CATEGORIES - categories, set())

    def test_runner_is_offline_and_integrates_known_case_corpus(self) -> None:
        report = run_benchmark_suite(ROOT, REGISTRY)

        self.assertFalse(report["networkUsed"])
        self.assertFalse(report["productionIntegration"])
        self.assertIn(report["gateDecision"], {"benchmark_suite_v2_ready", "benchmark_suite_v2_needs_more_real_cases"})
        self.assertGreaterEqual(report["summary"]["passCount"], 7)
        self.assertFalse(report["summary"]["phase3RuntimeAllowed"])

    def test_cli_writes_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "suite.json"
            exit_code = main(["--root", str(ROOT), "--registry", str(REGISTRY), "--output", str(output), "--quiet"])

            self.assertEqual(exit_code, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["reportType"], "inspoly_benchmark_suite_v2")
            self.assertFalse(payload["networkUsed"])

    def test_runner_is_not_imported_by_runtime_paths(self) -> None:
        for relative_path in (
            "app/scanner.py",
            "app/archive_scanner.py",
            "app/event_forensic.py",
            "app/browser_desktop.py",
            "app/storage.py",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("run_inspoly_benchmark_suite", source)


if __name__ == "__main__":
    unittest.main()
