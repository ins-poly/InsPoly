from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _tree(relative_path: str) -> ast.AST:
    return ast.parse(_read(relative_path), filename=relative_path)


def _imports_name(tree: ast.AST, module: str, name: str) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module != module:
            continue
        if any(alias.name == name for alias in node.names):
            return True
    return False


def _calls_name(tree: ast.AST, name: str) -> bool:
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == name
        for node in ast.walk(tree)
    )


def _slice_between(source: str, start: str, end: str) -> str:
    start_index = source.index(start)
    end_index = source.index(end, start_index)
    return source[start_index:end_index]


class CrossModeScoringContractTests(unittest.TestCase):
    def test_archive_and_event_forensic_reuse_shared_base_scorer(self) -> None:
        archive_tree = _tree("app/archive_scanner.py")
        event_tree = _tree("app/event_forensic.py")

        self.assertTrue(_imports_name(archive_tree, "app.scanner", "_score_trade"))
        self.assertTrue(_calls_name(archive_tree, "_score_trade"))
        self.assertTrue(_imports_name(event_tree, "app.scanner", "_score_trade"))
        self.assertTrue(_calls_name(event_tree, "_score_trade"))

    def test_event_forensic_replays_base_scorer_then_stores_overlay_score(self) -> None:
        event_tree = _tree("app/event_forensic.py")

        include_below_threshold_calls = [
            node
            for node in ast.walk(event_tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_score_trade"
            and any(
                keyword.arg == "include_below_threshold"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
                for keyword in node.keywords
            )
        ]
        self.assertTrue(include_below_threshold_calls)

        payload_contract_found = False
        for node in ast.walk(event_tree):
            if not isinstance(node, ast.Dict):
                continue
            keyed_values = {
                key.value: value
                for key, value in zip(node.keys, node.values)
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }
            existing_model_value = keyed_values.get("existingModelScore")
            event_forensic_value = keyed_values.get("eventForensicScore")
            if existing_model_value is None or event_forensic_value is None:
                continue
            if (
                isinstance(existing_model_value, ast.Attribute)
                and isinstance(existing_model_value.value, ast.Name)
                and existing_model_value.value.id == "case"
                and existing_model_value.attr == "suspicion_score"
                and isinstance(event_forensic_value, ast.Name)
                and event_forensic_value.id == "score"
            ):
                payload_contract_found = True
                break

        self.assertTrue(payload_contract_found)
        self.assertTrue(_calls_name(event_tree, "_event_forensic_score"))

    def test_archive_keeps_visible_and_excluded_archive_tiers(self) -> None:
        source = _read("app/archive_scanner.py")

        self.assertIn("def _visibility_tier_for_case", source)
        self.assertIn("visible_inclusion_status", source)
        self.assertIn("excluded_cases", source)
        self.assertIn('"Excluded"', source)

    def test_recent_scanner_keeps_saved_vs_quality_screened_visible_contract(self) -> None:
        backend = _read("app/browser_desktop.py")
        html = _read("app/browser_ui.html")

        self.assertIn("savedFlaggedCaseCount", backend)
        self.assertIn("visibleFlaggedCaseCount", backend)
        self.assertIn("serverHiddenCaseCount", backend)
        self.assertIn("quality-screened cards", html)
        self.assertIn("saved flagged total", html)
        self.assertIn("Base scanner score is the shared InsPoly suspicion score from _score_trade().", html)

    def test_event_forensic_browser_sort_filter_contract_is_local_to_loaded_rows(self) -> None:
        html = _read("app/browser_event_forensic_ui.html")
        sort_rows = _slice_between(html, "function sortRowsForTab", "function stripMarkdownMarkers")
        filter_rows = _slice_between(html, "function filterRowsForTab", "function dateTimeDatePart")

        self.assertIn('value: "forensic-desc"', html)
        self.assertIn('value: "existingModelScore-desc"', html)
        self.assertIn('value: "entryProbability-asc"', html)
        self.assertIn("numericValue(right.eventForensicScore) - numericValue(left.eventForensicScore)", sort_rows)
        self.assertIn(
            'if (mode === "existingModelScore-desc") return numericValue(right.existingModelScore) - numericValue(left.existingModelScore) || compareTradeConcern(left, right);',
            sort_rows,
        )
        self.assertIn(
            'if (mode === "entryProbability-asc") return tradeEntryProbabilitySortValue(left) - tradeEntryProbabilitySortValue(right) || compareTradeConcern(left, right);',
            sort_rows,
        )
        self.assertIn("const rows = filterRowsForTab(activeTab, baseRows, filters);", html)
        self.assertIn("sortRowsForTab(activeTab, rows, sortMode)", html)
        self.assertIn("parseProbabilityFilter(filters?.maxEntryProbability)", filter_rows)
        for local_only_source in (sort_rows, filter_rows):
            self.assertNotIn("/api/analyze", local_only_source)
            self.assertNotIn("postJson", local_only_source)
            self.assertNotIn("fetchJson", local_only_source)
            self.assertNotIn("open-output", local_only_source)

    def test_event_forensic_and_scanner_ui_copy_names_scores_clearly(self) -> None:
        event_html = _read("app/browser_event_forensic_ui.html")
        scanner_html = _read("app/browser_ui.html")

        self.assertIn("Event forensic priority (recommended)", event_html)
        self.assertIn("Base scanner score (diagnostic)", event_html)
        self.assertIn("Lowest entry price / implied probability", event_html)
        self.assertIn("Event concern", event_html)
        self.assertIn("Base scanner:", event_html)
        self.assertIn("existingModelScore", event_html)
        self.assertIn("eventForensicScore", event_html)
        self.assertIn("shared _score_trade() score (existingModelScore)", event_html)
        self.assertIn("Base scanner score is the shared InsPoly suspicion score", scanner_html)

    def test_docs_explain_cross_mode_contract_without_claiming_identical_modes(self) -> None:
        logic_doc = _read("docs/DETECTION_MODEL.md")
        program_doc = _read("docs/PROGRAMS.md")

        self.assertIn("## Cross-mode scoring contract", logic_doc)
        self.assertIn("`_score_trade()` in `app/scanner.py` is the shared base scorer", logic_doc)
        self.assertIn("Recent Scanner displays base-scanner cases after recent-mode visibility", logic_doc)
        self.assertIn("Archive Researcher reuses the base scorer", logic_doc)
        self.assertIn("stores `case.suspicion_score` as `existingModelScore`", logic_doc)
        self.assertIn("computes `eventForensicScore` as an event-local overlay", logic_doc)
        self.assertIn("Base scanner score", logic_doc)
        self.assertIn("Event forensic priority", logic_doc)
        self.assertIn("Event concern", logic_doc)
        self.assertIn("Archive visibility contract", program_doc)
        self.assertIn("visible_inclusion_status", program_doc)


if __name__ == "__main__":
    unittest.main()
