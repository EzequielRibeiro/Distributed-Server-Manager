#!/usr/bin/env python3

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"
DASHBOARD = ROOT / "dashboard"
for path in (ROOT, DATABASE, DASHBOARD):
    sys.path.insert(0, str(path))

from backend import DatabaseConfig
from backend_factory import create_backend
from location_admin_http import (
    DATACENTERS_PATH,
    REGIONS_PATH,
    dispatch_location_admin_get,
    dispatch_location_admin_post,
)


class LocationAdminHttpTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(
            DatabaseConfig(
                driver="sqlite",
                database=str(Path(self.temp.name) / "capivara.db"),
            )
        )
        self.backend.initialize()
        self.admin = {"role": "admin", "scope_id": None}

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_region_create_and_list(self):
        status, body = dispatch_location_admin_post(
            REGIONS_PATH,
            {"id": "local", "name": "Local"},
            user=self.admin,
            backend=self.backend,
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["id"], "local")

        status, body = dispatch_location_admin_get(
            REGIONS_PATH,
            user=self.admin,
            backend=self.backend,
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["regions"][0]["name"], "Local")

    def test_datacenter_create_and_list(self):
        dispatch_location_admin_post(
            REGIONS_PATH,
            {"id": "local", "name": "Local"},
            user=self.admin,
            backend=self.backend,
        )
        status, body = dispatch_location_admin_post(
            DATACENTERS_PATH,
            {"id": "local-default", "region_id": "local", "name": "Local Default"},
            user=self.admin,
            backend=self.backend,
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["name"], "Local Default")

        status, body = dispatch_location_admin_get(
            DATACENTERS_PATH,
            user=self.admin,
            backend=self.backend,
            region_id="local",
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(body["datacenters"]), 1)

    def test_customer_is_forbidden(self):
        status, _ = dispatch_location_admin_get(
            REGIONS_PATH,
            user={"role": "customer", "scope_id": "customer"},
            backend=self.backend,
        )
        self.assertEqual(status, 403)

    def test_unknown_path_is_not_claimed(self):
        self.assertIsNone(
            dispatch_location_admin_get(
                "/api/other",
                user=self.admin,
                backend=self.backend,
            )
        )


if __name__ == "__main__":
    unittest.main()
