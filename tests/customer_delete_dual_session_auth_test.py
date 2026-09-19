#!/usr/bin/env python3
"""Regression contract for dual-session Customer delete authentication."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
SERVER=(ROOT/"dashboard"/"server_part8.py").read_text(encoding="utf-8")
DELETE_JS=(ROOT/"dashboard"/"web"/"customer-instance-delete.js").read_text(encoding="utf-8")


class CustomerDeleteDualSessionAuthTest(unittest.TestCase):
    def test_customer_delete_sends_explicit_customer_area(self):
        self.assertIn('"X-Capivara-Auth-Area":"customer"',DELETE_JS)

    def test_legacy_integrated_auth_honors_explicit_customer_area(self):
        self.assertIn('explicit_area = str(headers.get("X-Capivara-Auth-Area") or "").strip().lower()',SERVER)
        self.assertIn('if explicit_area == "customer":',SERVER)
        self.assertIn('return integrated_customer_authenticate(headers)',SERVER)

    def test_legacy_integrated_auth_honors_explicit_controller_area(self):
        self.assertIn('if explicit_area == "controller":',SERVER)
        self.assertIn('return integrated_controller_authenticate(headers)',SERVER)

    def test_ambiguous_dual_session_without_area_still_fails_closed(self):
        self.assertIn("if controller is not None and customer is not None:",SERVER)
        self.assertIn("return None",SERVER)


if __name__=="__main__":
    unittest.main()
