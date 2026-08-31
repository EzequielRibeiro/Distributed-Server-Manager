#!/usr/bin/env python3
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AlertPageMutationGuardTest(unittest.TestCase):
    def test_alert_enhancement_uses_mutation_observer(self) -> None:
        js = (ROOT / "dashboard" / "web" / "alerts-page-enhancements.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("MutationObserver", js)
        self.assertIn("decorateAlertCards", js)


if __name__ == "__main__":
    unittest.main()
