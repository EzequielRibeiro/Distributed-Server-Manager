#!/usr/bin/env python3

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"
DASHBOARD = ROOT / "dashboard"
for path in (ROOT, DATABASE, DASHBOARD):
    sys.path.insert(0, str(path))

from backend import DatabaseConfig
from backend_factory import create_backend
from agent_runtime_repository import AgentRuntimeRepository
from location_repository import LocationRepository
from registry_repository import RegistryRepository
from placement_errors import PlacementUnavailable
from placement_service import choose_agent_for_instance


class AgentHeartbeatPlacementTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(
            DatabaseConfig(driver="sqlite", database=str(Path(self.temp.name) / "capivara.db"))
        )
        self.backend.initialize()
        RegistryRepository(self.backend).bootstrap_topology(
            controller_id="controller-main",
            controller_node_id="controller-node",
            controller_name="Controller",
            agent_id="agent-main",
            agent_node_id="agent-node",
            agent_name="Agent",
        )
        locations = LocationRepository(self.backend)
        locations.upsert_region(region_id="local", name="Local")
        locations.upsert_datacenter(
            datacenter_id="dc-local", region_id="local", name="Local Default"
        )
        locations.upsert_agent_location(agent_id="agent-main", datacenter_id="dc-local")
        self.runtime = AgentRuntimeRepository(self.backend)

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_legacy_agent_without_telemetry_remains_eligible(self):
        result = choose_agent_for_instance(self.backend, controller_id="controller-main")
        self.assertEqual(result["agent_id"], "agent-main")

    def test_offline_heartbeat_agent_is_not_selected(self):
        now = datetime.now(timezone.utc)
        self.runtime.heartbeat("agent-main", observed_at=now - timedelta(seconds=130))
        with self.assertRaises(PlacementUnavailable):
            choose_agent_for_instance(self.backend, controller_id="controller-main")

    def test_fresh_heartbeat_agent_is_selected(self):
        self.runtime.heartbeat("agent-main")
        result = choose_agent_for_instance(self.backend, controller_id="controller-main")
        self.assertEqual(result["agent_id"], "agent-main")


if __name__ == "__main__":
    unittest.main()
