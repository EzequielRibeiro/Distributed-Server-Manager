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
from location_admin_api import (
    list_datacenters_for_user,
    list_regions_for_user,
    upsert_datacenter_for_user,
    upsert_region_for_user,
)


class LocationAdminApiTest(unittest.TestCase):
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
        self.controller = {"role": "controller", "scope_id": "controller-one"}
        self.customer = {"role": "customer", "scope_id": "customer-one"}

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_admin_creates_region_without_coordinates(self):
        region = upsert_region_for_user(
            self.admin,
            self.backend,
            {
                "id": "br-se",
                "name": "Brasil Sudeste",
                "country": "br",
                "status": "active",
            },
        )
        self.assertEqual(region["id"], "br-se")
        self.assertEqual(region["name"], "Brasil Sudeste")
        self.assertEqual(region["country_code"], "BR")
        self.assertIsNone(region["latitude"])
        self.assertIsNone(region["longitude"])

    def test_admin_edits_region_and_can_disable_it(self):
        upsert_region_for_user(
            self.admin,
            self.backend,
            {"id": "local", "name": "Local"},
        )
        region = upsert_region_for_user(
            self.admin,
            self.backend,
            {
                "id": "local",
                "name": "Brasil Sudeste",
                "country_code": "BR",
                "status": "disabled",
            },
        )
        self.assertEqual(region["name"], "Brasil Sudeste")
        self.assertEqual(region["status"], "disabled")

    def test_admin_creates_datacenter_under_region(self):
        upsert_region_for_user(
            self.admin,
            self.backend,
            {"id": "br-se", "name": "Brasil Sudeste", "country_code": "BR"},
        )
        datacenter = upsert_datacenter_for_user(
            self.admin,
            self.backend,
            {
                "id": "limeira-horizon",
                "region_id": "br-se",
                "name": "Limeira / Horizon",
                "status": "active",
            },
        )
        self.assertEqual(datacenter["region_id"], "br-se")
        self.assertEqual(datacenter["name"], "Limeira / Horizon")
        self.assertIsNone(datacenter["latitude"])
        self.assertIsNone(datacenter["longitude"])

    def test_datacenter_requires_existing_region(self):
        with self.assertRaisesRegex(ValueError, "region not found"):
            upsert_datacenter_for_user(
                self.admin,
                self.backend,
                {"id": "dc", "region_id": "missing", "name": "DC"},
            )

    def test_controller_can_read_but_cannot_mutate_topology(self):
        upsert_region_for_user(
            self.admin,
            self.backend,
            {"id": "local", "name": "Local"},
        )
        self.assertEqual(len(list_regions_for_user(self.controller, self.backend)), 1)
        with self.assertRaises(PermissionError):
            upsert_region_for_user(
                self.controller,
                self.backend,
                {"id": "x", "name": "X"},
            )

    def test_customer_cannot_read_topology_administration(self):
        with self.assertRaises(PermissionError):
            list_regions_for_user(self.customer, self.backend)

    def test_active_only_filter_hides_disabled_records(self):
        upsert_region_for_user(
            self.admin,
            self.backend,
            {"id": "active", "name": "Active"},
        )
        upsert_region_for_user(
            self.admin,
            self.backend,
            {"id": "disabled", "name": "Disabled", "status": "disabled"},
        )
        regions = list_regions_for_user(
            self.admin,
            self.backend,
            active_only=True,
        )
        self.assertEqual([item["id"] for item in regions], ["active"])

    def test_coordinates_are_optional_but_validated_when_present(self):
        with self.assertRaisesRegex(ValueError, "latitude must be between"):
            upsert_region_for_user(
                self.admin,
                self.backend,
                {"id": "bad", "name": "Bad", "latitude": 91},
            )

    def test_datacenter_listing_can_filter_region(self):
        for region_id in ("a", "b"):
            upsert_region_for_user(
                self.admin,
                self.backend,
                {"id": region_id, "name": region_id.upper()},
            )
            upsert_datacenter_for_user(
                self.admin,
                self.backend,
                {
                    "id": f"dc-{region_id}",
                    "region_id": region_id,
                    "name": f"DC {region_id.upper()}",
                },
            )
        rows = list_datacenters_for_user(
            self.admin,
            self.backend,
            region_id="b",
        )
        self.assertEqual([item["id"] for item in rows], ["dc-b"])


if __name__ == "__main__":
    unittest.main()
