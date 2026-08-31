#!/usr/bin/env python3
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AlertPageMutationGuardTest(unittest.TestCase):
    def test_alert_enhancement_avoids_recursive_text_mutations(self) -> None:
        js = (ROOT / "dashboard" / "web" / "alerts-page-enhancements.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("MutationObserver", js)
        self.assertIn("decorateAlertCards", js)
        self.assertIn("if (label.textContent !== desired) label.textContent = desired;", js)
        self.assertIn("if (scope.textContent !== desired) scope.textContent = desired;", js)

    def test_alert_page_bumps_enhancement_cache_key(self) -> None:
        html = (ROOT / "dashboard" / "web" / "alerts.html").read_text(encoding="utf-8")
        self.assertIn('/alerts-page-enhancements.js?v=4', html)


if __name__ == "__main__":
    unittest.main()
