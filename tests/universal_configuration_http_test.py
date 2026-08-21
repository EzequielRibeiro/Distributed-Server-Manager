#!/usr/bin/env python3

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "core", ROOT / "database", ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backend import DatabaseConfig
from backend_factory import create_backend
from configuration_http import CONFIGURATIONS_PATH, dispatch_configuration_get, dispatch_configuration_post


class UniversalConfigurationHTTPTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(DatabaseConfig(driver="sqlite", database=str(Path(self.temp.name) / "capivara.db")))
        self.backend.initialize()
        self.admin = {"username": "admin", "role": "admin"}
        self.customer = {"username": "customer", "role": "customer"}

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_admin_can_create_get_list_and_resolve_global_configuration(self):
        status, result = dispatch_configuration_post(CONFIGURATIONS_PATH, {
            "scope_type": "global",
            "namespace": "runtime.defaults",
            "value": {"reconcile_interval_seconds": 15},
        }, user=self.admin, backend=self.backend)
        self.assertEqual(status, 201)
        self.assertEqual(result["configuration"]["revision"], 1)

        status, row = dispatch_configuration_get(
            CONFIGURATIONS_PATH,
            "scope=global&namespace=runtime.defaults",
            user=self.admin,
            backend=self.backend,
        )
        self.assertEqual(status, 200)
        self.assertEqual(row["value"]["reconcile_interval_seconds"], 15)

        status, listing = dispatch_configuration_get(CONFIGURATIONS_PATH, "scope=global", user=self.admin, backend=self.backend)
        self.assertEqual(status, 200)
        self.assertEqual(listing["count"], 1)

    def test_customer_is_forbidden(self):
        status, _ = dispatch_configuration_get(CONFIGURATIONS_PATH, "", user=self.customer, backend=self.backend)
        self.assertEqual(status, 403)
        status, _ = dispatch_configuration_post(CONFIGURATIONS_PATH, {
            "scope_type": "global", "namespace": "runtime.defaults", "value": {}
        }, user=self.customer, backend=self.backend)
        self.assertEqual(status, 403)

    def test_raw_secret_returns_controlled_error(self):
        status, result = dispatch_configuration_post(CONFIGURATIONS_PATH, {
            "scope_type": "global",
            "namespace": "mail.smtp",
            "value": {"password": "do-not-store"},
        }, user=self.admin, backend=self.backend)
        self.assertEqual(status, 400)
        self.assertEqual(result["error"], "invalid_request")


if __name__ == "__main__":
    unittest.main()
