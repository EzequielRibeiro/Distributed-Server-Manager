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
from registry import installation_profile_identity
from registry_repository import InfrastructureIdentityConflict, RegistryRepository


class InstallationProfileBootstrapTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp.name) / "capivara.db"
        self.backend = create_backend(
            DatabaseConfig(
                driver="sqlite",
                database=str(self.database_path),
            )
        )
        self.backend.initialize()
        self.repository = RegistryRepository(self.backend)

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def query(self, sql, parameters=()):
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            return connection.execute(sql, parameters).fetchall()
        finally:
            connection.close()

    def test_controller_bootstrap_creates_controller_without_agent(self):
        result = installation_profile_identity(
            self.repository,
            profile="controller",
            hostname="controller-one",
        )

        self.assertEqual(result["node_id"], "controller-one")
        self.assertEqual(result["controller_id"], "controller-controller-one")
        self.assertIsNone(result["agent_id"])
        self.assertFalse(result["placement_ready"])

        nodes = self.query("SELECT id,role,status FROM nodes")
        controllers = self.query("SELECT id,node_id,status FROM controllers")
        agents = self.query("SELECT id FROM agents")
        self.assertEqual(
            [tuple(row) for row in nodes],
            [("controller-one", "controller", "active")],
        )
        self.assertEqual(
            [tuple(row) for row in controllers],
            [("controller-controller-one", "controller-one", "active")],
        )
        self.assertEqual(agents, [])

    def test_standalone_agent_creates_pending_local_identity_only(self):
        result = installation_profile_identity(
            self.repository,
            profile="agent",
            hostname="agent-one",
        )

        self.assertEqual(result["agent_id"], "agent-agent-one")
        self.assertEqual(result["agent_status"], "pending")
        self.assertTrue(result["awaiting_pairing"])
        self.assertFalse(result["registered_with_controller"])
        self.assertFalse(result["placement_ready"])

        nodes = self.query("SELECT id,role,status FROM nodes")
        controllers = self.query("SELECT id FROM controllers")
        agents = self.query("SELECT id FROM agents")
        self.assertEqual(
            [tuple(row) for row in nodes],
            [("agent-one", "agent", "pending")],
        )
        self.assertEqual(controllers, [])
        self.assertEqual(agents, [])

    def test_hybrid_bootstrap_is_immediately_placement_ready(self):
        result = installation_profile_identity(
            self.repository,
            profile="hybrid",
            hostname="hybrid-one",
        )

        self.assertEqual(result["controller_id"], "controller-hybrid-one")
        self.assertEqual(result["agent_id"], "agent-hybrid-one")
        self.assertEqual(result["agent_status"], "active")
        self.assertEqual(result["topology_state"], "ready")
        self.assertTrue(result["placement_ready"])

        nodes = self.query("SELECT id,role,status FROM nodes")
        self.assertEqual(
            [tuple(row) for row in nodes],
            [("hybrid-one", "hybrid", "active")],
        )

        candidates = LocationRepository(self.backend).candidates(
            "controller-hybrid-one"
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["agent_id"], "agent-hybrid-one")

    def test_hybrid_reinstall_preserves_offline_agent_state(self):
        installation_profile_identity(
            self.repository,
            profile="hybrid",
            hostname="hybrid-two",
        )
        connection = sqlite3.connect(self.database_path)
        try:
            connection.execute(
                "UPDATE agents SET status='offline' WHERE id='agent-hybrid-two'"
            )
            connection.commit()
        finally:
            connection.close()

        result = installation_profile_identity(
            self.repository,
            profile="hybrid",
            hostname="hybrid-two",
        )

        self.assertEqual(result["agent_status"], "offline")
        self.assertFalse(result["placement_ready"])
        self.assertEqual(
            LocationRepository(self.backend).candidates("controller-hybrid-two"),
            [],
        )

    def test_profile_bootstrap_rejects_role_collision(self):
        installation_profile_identity(
            self.repository,
            profile="controller",
            hostname="same-node",
        )

        with self.assertRaises(InfrastructureIdentityConflict):
            installation_profile_identity(
                self.repository,
                profile="agent",
                hostname="same-node",
            )


if __name__ == "__main__":
    unittest.main()
