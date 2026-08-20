#!/usr/bin/env python3
"""CLI/service contract tests for Controller -> Hybrid role administration."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "database"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from backend import DatabaseConfig
from backend_factory import create_backend
from infrastructure_role_cli import promote_local_controller, role_status
from registry import installation_profile_identity
from registry_repository import RegistryRepository


class InfrastructureRoleCliTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "capivara.db"
        self.backend = create_backend(DatabaseConfig(driver="sqlite", database=str(self.db_path)))
        self.repository = RegistryRepository(self.backend)
        self.identity = installation_profile_identity(
            self.repository,
            profile="controller",
            hostname="role-cli-host",
        )

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_show_reports_controller_before_promotion(self):
        payload = role_status(self.repository, node_id="role-cli-host")
        self.assertEqual(payload["role"], "controller")
        self.assertEqual(payload["controller_id"], "controller-role-cli-host")
        self.assertIsNone(payload["agent_id"])

    def test_set_hybrid_preserves_controller_and_creates_agent(self):
        before_controller = self.identity["controller_id"]
        result = promote_local_controller(
            self.repository,
            node_id="role-cli-host",
        )
        after = role_status(self.repository, node_id="role-cli-host")

        self.assertTrue(result["changed"])
        self.assertEqual(result["previous_role"], "controller")
        self.assertEqual(result["node_role"], "hybrid")
        self.assertEqual(result["controller_id"], before_controller)
        self.assertEqual(result["agent_id"], "agent-role-cli-host")
        self.assertTrue(result["runtime_reconciliation_required"])
        self.assertEqual(after["role"], "hybrid")
        self.assertEqual(after["controller_id"], before_controller)
        self.assertEqual(after["agent_id"], "agent-role-cli-host")

    def test_repeated_set_hybrid_is_idempotent(self):
        first = promote_local_controller(self.repository, node_id="role-cli-host")
        second = promote_local_controller(self.repository, node_id="role-cli-host")

        self.assertTrue(first["changed"])
        self.assertFalse(second["changed"])
        self.assertEqual(second["previous_role"], "hybrid")
        self.assertEqual(second["agent_id"], first["agent_id"])

        with self.repository.transaction() as session:
            agents = session.execute(
                "SELECT id FROM agents WHERE node_id=?",
                ("role-cli-host",),
            ).fetchall()
            controllers = session.execute(
                "SELECT id FROM controllers WHERE node_id=?",
                ("role-cli-host",),
            ).fetchall()
        self.assertEqual(len(agents), 1)
        self.assertEqual(len(controllers), 1)


if __name__ == "__main__":
    unittest.main()
