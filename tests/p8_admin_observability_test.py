#!/usr/bin/env python3
"""Contract tests for P8 consolidated administrative observability."""

from __future__ import annotations

import unittest
from pathlib import Path

from dashboard.admin_observability_api import _count_by, _require_admin

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"


class P8AdministrativeObservabilityContractTest(unittest.TestCase):
    def test_admin_and_controller_are_authorized(self):
        self.assertEqual(_require_admin({"role": "admin"})["role"], "admin")
        self.assertEqual(_require_admin({"role": "controller"})["role"], "controller")

    def test_customer_and_operator_are_denied(self):
        for role in ("customer", "operator", ""):
            with self.assertRaises(PermissionError):
                _require_admin({"role": role})

    def test_status_counts_are_deterministic(self):
        rows = [{"status": "online"}, {"status": "offline"}, {"status": "online"}, {}]
        self.assertEqual(_count_by(rows, "status"), {"offline": 1, "online": 2, "unknown": 1})


    def test_static_assets_bypass_legacy_page_auth_gate(self):
        source = (DASHBOARD / "admin_observability_http.py").read_text(encoding="utf-8")
        self.assertIn('ADMIN_OBSERVABILITY_ASSETS = {"/admin-observability.js", "/admin-observability.css"}', source)
        asset_index = source.index("if parsed.path in ADMIN_OBSERVABILITY_ASSETS:")
        page_auth_index = source.index("user = authenticate(self.headers)", asset_index)
        self.assertLess(asset_index, page_auth_index)
        self.assertIn("self.send_file(legacy.STATIC_FILES[parsed.path])", source)

    def test_browser_requests_use_controller_session_boundary(self):
        script = (DASHBOARD / "web" / "admin-observability.js").read_text(encoding="utf-8")
        self.assertIn("'X-Capivara-Auth-Area':'controller'", script)
        self.assertIn("credentials:'same-origin'", script)
        self.assertIn("cache:'no-store'", script)


if __name__ == "__main__":
    unittest.main()
