#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "database"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from agent_admin_repository import AgentAdminRepository
from agent_pairing_repository import AgentPairingRepository
from backend import DatabaseConfig
from backend_factory import create_backend
from registry import installation_profile_identity
from registry_repository import RegistryRepository


class AgentAdminRemovalTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(
            DatabaseConfig(driver="sqlite", database=str(Path(self.temp.name) / "capivara.db"))
        )
        identity = installation_profile_identity(
            RegistryRepository(self.backend),
            profile="controller",
            hostname="agent-removal-controller",
        )
        self.controller_id = str(identity["controller_id"])
        self.pairing = AgentPairingRepository(self.backend)
        self.agent_id = "agent-remove-test"
        self.node_id = "node-remove-test"
        self.fingerprint = "sha256:agent-remove-test"
        token = self.pairing.issue_token(controller_id=self.controller_id, created_by="test")
        self.enrolled = self.pairing.enroll(
            pairing_token=token.token,
            agent_id=self.agent_id,
            node_id=self.node_id,
            name="Agent Removível",
            fingerprint=self.fingerprint,
            hostname="remove-host",
            os_name="linux",
            architecture="x86_64",
            address="192.0.2.55",
        )
        self.admin = AgentAdminRepository(self.backend)

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def count(self, table: str, column: str, value: str) -> int:
        with self.backend.connect() as connection:
            row = connection.execute(
                f"SELECT COUNT(*) AS n FROM {table} WHERE {column}=?",
                (value,),
            ).fetchone()
        return int(row["n"])

    def test_remove_deletes_agent_node_and_cascaded_runtime_identity(self):
        result = self.admin.remove(
            self.agent_id,
            confirmation=self.agent_id,
            actor="admin",
        )

        self.assertTrue(result["removed"])
        self.assertEqual(result["agent_id"], self.agent_id)
        self.assertEqual(result["node_id"], self.node_id)
        self.assertEqual(result["removed_by"], "admin")
        self.assertEqual(self.count("agents", "id", self.agent_id), 0)
        self.assertEqual(self.count("nodes", "id", self.node_id), 0)
        self.assertEqual(self.count("agent_credentials", "agent_id", self.agent_id), 0)
        self.assertEqual(self.count("agent_runtime_inventory", "agent_id", self.agent_id), 0)

    def test_remove_requires_exact_agent_id_confirmation(self):
        with self.assertRaisesRegex(ValueError, "confirmation must exactly match agent_id"):
            self.admin.remove(self.agent_id, confirmation="remove", actor="admin")
        self.assertEqual(self.count("agents", "id", self.agent_id), 1)
        self.assertEqual(self.count("nodes", "id", self.node_id), 1)

    def test_remove_is_blocked_while_node_has_instances(self):
        with self.backend.transaction() as connection:
            connection.execute(
                "INSERT INTO instances(id,node_id,game_id,name,status) VALUES (?,?,?,?,?)",
                ("instance-remove-blocker", self.node_id, "minecraft", "Servidor teste", "offline"),
            )

        with self.assertRaisesRegex(ValueError, "cannot be removed"):
            self.admin.remove(self.agent_id, confirmation=self.agent_id, actor="admin")

        self.assertEqual(self.count("agents", "id", self.agent_id), 1)
        self.assertEqual(self.count("nodes", "id", self.node_id), 1)

    def test_same_physical_identity_can_enroll_again_after_removal(self):
        self.admin.remove(self.agent_id, confirmation=self.agent_id, actor="admin")
        token = self.pairing.issue_token(controller_id=self.controller_id, created_by="admin")
        reenrolled = self.pairing.enroll(
            pairing_token=token.token,
            agent_id=self.agent_id,
            node_id=self.node_id,
            name="Agent Reinstalado",
            fingerprint=self.fingerprint,
            hostname="remove-host",
            os_name="linux",
            architecture="x86_64",
            address="192.0.2.55",
        )
        self.assertEqual(reenrolled.agent_id, self.agent_id)
        self.assertEqual(reenrolled.node_id, self.node_id)
        self.assertEqual(self.count("agents", "id", self.agent_id), 1)
        self.assertEqual(self.count("nodes", "id", self.node_id), 1)

    def test_dashboard_contract_exposes_admin_only_removal(self):
        html = (ROOT / "dashboard" / "web" / "agent-details.html").read_text(encoding="utf-8")
        js = (ROOT / "dashboard" / "web" / "agent-details.js").read_text(encoding="utf-8")
        http = (ROOT / "dashboard" / "agent_admin_http.py").read_text(encoding="utf-8")
        self.assertIn('id="agent-danger-zone"', html)
        self.assertIn('class="cap-admin-card admin-only"', html)
        self.assertIn('id="agent-remove-confirmation"', html)
        self.assertIn('id="agent-remove"', html)
        self.assertIn('/api/admin/agent/remove', js)
        self.assertIn('currentRole!=="admin"', js)
        self.assertIn('REMOVE_PATH = "/api/admin/agent/remove"', http)
        self.assertIn('Somente administradores podem remover Agents', http)


if __name__ == "__main__":
    unittest.main()
