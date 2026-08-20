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

from agent_location_api import set_agent_location_for_user
from backend import DatabaseConfig
from backend_factory import create_backend
from location_admin_api import upsert_datacenter_for_user, upsert_region_for_user
from location_repository import LocationRepository
from registry import installation_profile_identity
from registry_repository import RegistryRepository


class Phase4TopologyIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(
            DatabaseConfig(
                driver="sqlite",
                database=str(Path(self.temp.name) / "capivara.db"),
            )
        )
        self.backend.initialize()
        self.registry = RegistryRepository(self.backend)
        self.admin = {"role": "admin", "scope_id": None}

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_hybrid_bootstrap_creates_neutral_topology_without_coordinates(self):
        result = installation_profile_identity(
            self.registry,
            profile="hybrid",
            hostname="horizon-server",
        )
        self.assertTrue(result["placement_ready"])

        locations = LocationRepository(self.backend)
        regions = locations.regions()
        datacenters = locations.datacenters()
        self.assertEqual(len(regions), 1)
        self.assertEqual(regions[0]["name"], "Local")
        self.assertIsNone(regions[0]["latitude"])
        self.assertIsNone(regions[0]["longitude"])
        self.assertEqual(len(datacenters), 1)
        self.assertEqual(datacenters[0]["name"], "Local Default")
        self.assertIsNone(datacenters[0]["latitude"])
        self.assertIsNone(datacenters[0]["longitude"])

        candidate = locations.candidates("controller-horizon-server")[0]
        self.assertEqual(candidate["agent_id"], "agent-horizon-server")

    def test_admin_can_replace_neutral_topology_without_coordinates(self):
        installation_profile_identity(
            self.registry,
            profile="hybrid",
            hostname="horizon-server",
        )

        upsert_region_for_user(
            self.admin,
            self.backend,
            {
                "id": "br-se",
                "name": "Brasil Sudeste",
                "country_code": "BR",
            },
        )
        upsert_datacenter_for_user(
            self.admin,
            self.backend,
            {
                "id": "limeira-horizon",
                "region_id": "br-se",
                "name": "Limeira / Horizon",
            },
        )
        set_agent_location_for_user(
            self.admin,
            self.backend,
            {
                "agent_id": "agent-horizon-server",
                "datacenter_id": "limeira-horizon",
            },
        )

        candidates = LocationRepository(self.backend).candidates(
            "controller-horizon-server"
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["region_name"], "Brasil Sudeste")
        self.assertEqual(candidates[0]["datacenter_name"], "Limeira / Horizon")
        self.assertIsNone(candidates[0]["latitude"])
        self.assertIsNone(candidates[0]["longitude"])

    def test_disabling_any_topology_level_removes_agent_from_placement(self):
        installation_profile_identity(
            self.registry,
            profile="hybrid",
            hostname="node-one",
        )
        locations = LocationRepository(self.backend)
        self.assertEqual(len(locations.candidates("controller-node-one")), 1)

        upsert_region_for_user(
            self.admin,
            self.backend,
            {
                "id": "region-local-node-one",
                "name": "Local",
                "status": "disabled",
            },
        )
        self.assertEqual(locations.candidates("controller-node-one"), [])

        upsert_region_for_user(
            self.admin,
            self.backend,
            {
                "id": "region-local-node-one",
                "name": "Local",
                "status": "active",
            },
        )
        upsert_datacenter_for_user(
            self.admin,
            self.backend,
            {
                "id": "datacenter-local-node-one",
                "region_id": "region-local-node-one",
                "name": "Local Default",
                "status": "disabled",
            },
        )
        self.assertEqual(locations.candidates("controller-node-one"), [])


if __name__ == "__main__":
    unittest.main()
