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

from core.agent_lifecycle import transition_agent
from backend import DatabaseConfig
from backend_factory import create_backend
from agent_registration_repository import AgentRegistrationRepository
from agent_heartbeat_api import record_agent_heartbeat
from registry_repository import RegistryRepository


class AgentPhase9LifecycleTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(
            DatabaseConfig(driver="sqlite", database=str(Path(self.temp.name) / "capivara.db"))
        )
        self.backend.initialize()
        RegistryRepository(self.backend).bootstrap_installation_profile(
            profile="controller",
            node_id="controller-node",
            node_name="Controller",
            controller_id="controller-main",
            controller_name="Controller",
        )

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_discovered_is_first_class_lifecycle_state(self):
        registered = AgentRegistrationRepository(self.backend).discover(
            controller_id="controller-main",
            agent_id="agent-new",
            node_id="node-new",
            name="New Agent",
        )
        self.assertEqual(registered.status, "discovered")
        self.assertEqual(transition_agent("discovered", "pending").target, "pending")

    def test_heartbeat_rejects_claimed_identity_mismatch(self):
        AgentRegistrationRepository(self.backend).register(
            controller_id="controller-main",
            agent_id="agent-new",
            node_id="node-new",
            name="New Agent",
        )
        with self.assertRaises(PermissionError):
            record_agent_heartbeat(
                "agent-new",
                {"agent_id": "other-agent"},
                backend=self.backend,
            )

    def test_heartbeat_records_inventory(self):
        AgentRegistrationRepository(self.backend).register(
            controller_id="controller-main",
            agent_id="agent-new",
            node_id="node-new",
            name="New Agent",
        )
        result = record_agent_heartbeat(
            "agent-new",
            {
                "agent_id": "agent-new",
                "hostname": "node-a",
                "os": "Linux",
                "architecture": "x86_64",
                "capivara_version": "1.4.3",
                "address": "203.0.113.10",
                "fingerprint": "sha256:agent-new",
                "capabilities": {"steamcmd": True},
                "cpu": {"cores": 8},
                "ram_total_bytes": 34359738368,
                "storage": {"free_bytes": 1000000000},
            },
            backend=self.backend,
        )
        self.assertEqual(result["health_status"], "online")
        self.assertTrue(result["last_seen"].endswith("Z"))


if __name__ == "__main__":
    unittest.main()
