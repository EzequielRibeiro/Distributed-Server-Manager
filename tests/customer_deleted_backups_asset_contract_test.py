#!/usr/bin/env python3
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CustomerDeletedBackupsAssetContractTest(unittest.TestCase):
    def test_server_part8_keeps_javascript_asset_protected(self):
        text = (ROOT / "dashboard" / "server_part8.py").read_text(encoding="utf-8")
        self.assertIn('if path=="/customer-deleted-backups.js":', text)
        self.assertIn('self.send_file(legacy.WEB_DIR/"customer-deleted-backups.js")', text)
        self.assertIn('if not _require_area_role(self,user,{"customer"}):return', text)

    def test_runtime_entrypoint_patches_part8_authentication_with_session_bridge(self):
        text = (ROOT / "dashboard" / "server_part10.py").read_text(encoding="utf-8")
        self.assertIn("session_user_from_headers", text)
        self.assertIn("authenticate_browser_customer", text)
        self.assertIn("part8.integrated_authenticate = integrated_customer_authenticate", text)

    def test_asset_exists_as_javascript_source(self):
        path = ROOT / "dashboard" / "web" / "customer-deleted-backups.js"
        self.assertTrue(path.is_file())
        text = path.read_text(encoding="utf-8")
        self.assertIn('"use strict"', text)


if __name__ == "__main__":
    unittest.main()
