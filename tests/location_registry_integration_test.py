#!/usr/bin/env python3

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"

sys.path.insert(0, str(DATABASE))


from backend import DatabaseConfig
from backend_factory import create_backend
from location_repository import LocationRepository
from registry_repository import RegistryRepository


class LocationRegistryIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()

        self.database_path = (
            Path(self.temp.name) / "capivara.db"
        )

        self.backend = create_backend(
            DatabaseConfig(
                driver="sqlite",
                database=str(self.database_path),
            )
        )

        self.registry = RegistryRepository(self.backend)
        self.locations = LocationRepository(self.backend)

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def bootstrap_agent(self):
        return self.registry.bootstrap_topology(
            controller_id="controller-main",
            controller_node_id="controller-node",
            controller_name="Controlador Principal",
            agent_id="agent-main",
            agent_node_id="agent-node",
            agent_name="Agente Principal",
        )

    def create_location(self):
        self.locations.upsert_region(
            region_id="br-se",
            name="Brasil Sudeste",
            country_code="BR",
            continent_code="SA",
            latitude=-23.5,
            longitude=-46.6,
        )

        self.locations.upsert_datacenter(
            datacenter_id="dc-sp",
            region_id="br-se",
            name="Sao Paulo",
            provider="test",
            city="Sao Paulo",
            country_code="BR",
            latitude=-23.5,
            longitude=-46.6,
        )

    def test_bootstrap_agent_can_remain_unplaced(self):
        payload = self.bootstrap_agent()

        self.assertEqual(
            payload["agent_id"],
            "agent-main",
        )

        candidates = self.locations.candidates(
            "controller-main"
        )

        self.assertEqual(candidates, [])

    def test_bootstrapped_agent_can_receive_location(self):
        self.bootstrap_agent()
        self.create_location()

        self.locations.upsert_agent_location(
            agent_id="agent-main",
            datacenter_id="dc-sp",
            public_host="agent.example.test",
        )

        candidates = self.locations.candidates(
            "controller-main"
        )

        self.assertEqual(len(candidates), 1)

        candidate = candidates[0]

        self.assertEqual(
            candidate["agent_id"],
            "agent-main",
        )
        self.assertEqual(
            candidate["node_id"],
            "agent-node",
        )
        self.assertEqual(
            candidate["region_id"],
            "br-se",
        )
        self.assertEqual(
            candidate["datacenter_id"],
            "dc-sp",
        )
        self.assertEqual(
            candidate["public_host"],
            "agent.example.test",
        )
        self.assertEqual(
            candidate["instance_count"],
            0,
        )

    def test_location_assignment_is_idempotent(self):
        self.bootstrap_agent()
        self.create_location()

        arguments = {
            "agent_id": "agent-main",
            "datacenter_id": "dc-sp",
            "public_host": "agent.example.test",
        }

        self.locations.upsert_agent_location(**arguments)
        self.locations.upsert_agent_location(**arguments)

        candidates = self.locations.candidates(
            "controller-main"
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(
            candidates[0]["agent_id"],
            "agent-main",
        )

    def test_agent_can_be_relocated(self):
        self.bootstrap_agent()
        self.create_location()

        self.locations.upsert_datacenter(
            datacenter_id="dc-rj",
            region_id="br-se",
            name="Rio de Janeiro",
            provider="test",
            city="Rio de Janeiro",
            country_code="BR",
            latitude=-22.9,
            longitude=-43.2,
        )

        self.locations.upsert_agent_location(
            agent_id="agent-main",
            datacenter_id="dc-sp",
        )

        self.locations.upsert_agent_location(
            agent_id="agent-main",
            datacenter_id="dc-rj",
        )

        candidates = self.locations.candidates(
            "controller-main"
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(
            candidates[0]["datacenter_id"],
            "dc-rj",
        )
        self.assertEqual(
            candidates[0]["datacenter_name"],
            "Rio de Janeiro",
        )

    def test_location_cannot_reference_unknown_agent(self):
        self.locations.initialize()
        self.create_location()

        with self.assertRaises(Exception):
            self.locations.upsert_agent_location(
                agent_id="agent-does-not-exist",
                datacenter_id="dc-sp",
            )


if __name__ == "__main__":
    unittest.main()
