#!/usr/bin/env python3

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"
for path in (ROOT, DATABASE):
    sys.path.insert(0, str(path))

from backend import DatabaseConfig
from backend_factory import create_backend
from location_repository import LocationRepository
from registry_repository import RegistryRepository


class PlacementStatusRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp.name) / "capivara.db"
        self.backend = create_backend(
            DatabaseConfig(driver="sqlite", database=str(self.database_path))
        )
        self.backend.initialize()
        self.registry = RegistryRepository(self.backend)
        self.locations = LocationRepository(self.backend)

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def execute(self, sql, parameters=()):
        connection = sqlite3.connect(self.database_path)
        try:
            connection.execute(sql, parameters)
            connection.commit()
        finally:
            connection.close()

    def bootstrap_agent(self):
        self.registry.bootstrap_topology(
            controller_id="controller-main",
            controller_node_id="controller-node",
            controller_name="Controller Main",
            agent_id="agent-main",
            agent_node_id="agent-node",
            agent_name="Agent Main",
        )

    def test_empty_registry_reports_no_agents(self):
        status = self.registry.topology_status()
        self.assertEqual(status["controllers"], 0)
        self.assertEqual(status["agents"], 0)
        self.assertEqual(status["regions"], 0)
        self.assertEqual(status["datacenters"], 0)
        self.assertEqual(status["agent_locations"], 0)
        self.assertEqual(status["eligible_agents"], 0)
        self.assertFalse(status["placement_ready"])
        self.assertEqual(status["placement_reason"], "no_agents")
        self.assertEqual(status["placement_reasons"], ["no_agents"])

    def test_pending_agent_reports_all_missing_topology_levels(self):
        self.bootstrap_agent()
        self.execute("UPDATE agents SET status='pending' WHERE id='agent-main'")

        status = self.registry.topology_status()
        self.assertEqual(status["agents"], 1)
        self.assertEqual(status["pending_agents"], 1)
        self.assertEqual(status["unlocated_agents"], 1)
        self.assertEqual(status["eligible_agents"], 0)
        self.assertEqual(
            status["placement_reasons"],
            [
                "agent_pending",
                "missing_location",
                "missing_datacenter",
                "missing_region",
                "no_eligible_agents",
            ],
        )

    def test_region_without_datacenter_reports_missing_datacenter(self):
        self.bootstrap_agent()
        self.locations.upsert_region(region_id="local", name="Local")

        status = self.registry.topology_status()
        self.assertIn("missing_location", status["placement_reasons"])
        self.assertIn("missing_datacenter", status["placement_reasons"])
        self.assertNotIn("missing_region", status["placement_reasons"])
        self.assertEqual(status["eligible_agents"], 0)

    def test_datacenter_without_agent_location_reports_missing_location(self):
        self.bootstrap_agent()
        self.locations.upsert_region(region_id="local", name="Local")
        self.locations.upsert_datacenter(
            datacenter_id="local-default",
            region_id="local",
            name="Local Default",
        )

        status = self.registry.topology_status()
        self.assertEqual(status["regions"], 1)
        self.assertEqual(status["datacenters"], 1)
        self.assertEqual(status["agent_locations"], 0)
        self.assertEqual(
            status["placement_reasons"],
            ["missing_location", "no_eligible_agents"],
        )

    def test_complete_active_chain_is_placement_ready(self):
        self.bootstrap_agent()
        self.locations.upsert_region(region_id="local", name="Local")
        self.locations.upsert_datacenter(
            datacenter_id="local-default",
            region_id="local",
            name="Local Default",
        )
        self.locations.upsert_agent_location(
            agent_id="agent-main",
            datacenter_id="local-default",
        )

        status = self.registry.topology_status()
        self.assertEqual(status["controllers"], 1)
        self.assertEqual(status["agents"], 1)
        self.assertEqual(status["regions"], 1)
        self.assertEqual(status["datacenters"], 1)
        self.assertEqual(status["agent_locations"], 1)
        self.assertEqual(status["eligible_agents"], 1)
        self.assertTrue(status["placement_ready"])
        self.assertIsNone(status["placement_reason"])
        self.assertEqual(status["placement_reasons"], [])

    def test_inactive_chain_has_no_eligible_agents(self):
        self.bootstrap_agent()
        self.locations.upsert_region(region_id="local", name="Local")
        self.locations.upsert_datacenter(
            datacenter_id="local-default",
            region_id="local",
            name="Local Default",
        )
        self.locations.upsert_agent_location(
            agent_id="agent-main",
            datacenter_id="local-default",
        )
        self.locations.upsert_region(
            region_id="local",
            name="Local",
            status="disabled",
        )

        status = self.registry.topology_status()
        self.assertFalse(status["placement_ready"])
        self.assertEqual(status["eligible_agents"], 0)
        self.assertEqual(status["placement_reasons"], ["no_eligible_agents"])


if __name__ == "__main__":
    unittest.main()
