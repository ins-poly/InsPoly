from __future__ import annotations

from pathlib import Path
import unittest

from app.scanner import DOMAIN_BY_CATEGORY
from app.site_categories import SITE_CATEGORY_CANDIDATES, category_sensitivity


class SiteCategoryTests(unittest.TestCase):
    def test_current_polymarket_visible_topics_are_configured(self) -> None:
        configured = dict(SITE_CATEGORY_CANDIDATES)
        expected = {
            "Esports": "esports",
            "Iran": "iran",
            "Geopolitics": "geopolitics",
            "Tech": "tech",
            "Weather": "weather",
            "Mentions": "mention-markets",
        }
        for label, slug in expected.items():
            self.assertEqual(configured.get(label), slug)

    def test_new_categories_have_sensitivity_and_domain_mapping(self) -> None:
        for label in ["Esports", "Iran", "Geopolitics", "Tech", "Weather", "Mentions"]:
            points, reason = category_sensitivity(label)
            self.assertIsInstance(points, int)
            self.assertGreaterEqual(points, 1)
            self.assertNotIn("default", reason.lower())
            self.assertIn(label, DOMAIN_BY_CATEGORY)

    def test_browser_ui_exposes_topic_bulk_actions(self) -> None:
        html = Path("app/browser_ui.html").read_text(encoding="utf-8")
        self.assertIn("Select all", html)
        self.assertIn("Select none", html)
        self.assertIn("selectAllTopics", html)
        self.assertIn("clearTopics", html)


if __name__ == "__main__":
    unittest.main()
