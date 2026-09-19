#!/usr/bin/env python3
"""Regression contracts for protected HTML cache policy and cap-only updater validation."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "dashboard" / "server_part8.py").read_text(encoding="utf-8")
UPDATER = (ROOT / "update.sh").read_text(encoding="utf-8")


class ProtectedHtmlCachePolicyTest(unittest.TestCase):
    def test_protected_html_sender_disables_browser_cache(self):
        marker = "def _send_html"
        start = SERVER.index(marker)
        end = SERVER.index("\ndef _serve_instance_page", start)
        source = SERVER[start:end]
        self.assertIn('send_header("Cache-Control","no-store")', source)
        self.assertIn('send_header("Pragma","no-cache")', source)
        self.assertIn('send_header("Expires","0")', source)

    def test_customer_pages_use_protected_html_sender(self):
        self.assertIn('def _serve_instance_page(self):_send_html(', SERVER)
        self.assertIn('def _serve_customer_page(self):_send_html(', SERVER)
        self.assertIn('def _serve_controller_page(self):_send_html(', SERVER)


class CapOnlyUpdaterValidationTest(unittest.TestCase):
    def test_final_validation_requires_cap_not_retired_dsm(self):
        match = re.search(
            r"validate_final_installation\(\) \{(?P<body>.*?)\n\}",
            UPDATER,
            flags=re.S,
        )
        self.assertIsNotNone(match)
        body = match.group("body")
        self.assertIn('"${INSTALL_DIR}/bin/cap"', body)
        self.assertNotIn('"${INSTALL_DIR}/bin/dsm"', body)

    def test_global_installer_removes_retired_dsm_alias(self):
        self.assertIn("rm -f -- /usr/local/bin/dsm", UPDATER)


if __name__ == "__main__":
    unittest.main()
