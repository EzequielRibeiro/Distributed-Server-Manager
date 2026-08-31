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

from agent_pairing_repository import AgentPairingRepository
from agent_uninstall_repository import AgentUninstallRepository
from backend import DatabaseConfig
from backend_factory import create_backend
from registry import installation_profile_identity
from registry_repository import RegistryRepository


class AgentRemoteUninstallTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(DatabaseConfig(driver="sqlite", database=str(Path(self.temp.name) / "capivara.db")))
        controller_id = installation_profile_identity(
            RegistryRepository(self.backend),
            profile="controller",
            hostname="uninstall-controller",
        )["controller_id"]
        pairing = AgentPairingRepository(self.backend)
        token = pairing.issue_token(controller_id=controller_id, created_by="test")
        pairing.enroll(
            pairing_token=token.token,
            agent_id="agent-uninstall-test",
            node_id="node-uninstall-test",
            name="Windows Agent",
            fingerprint="sha256:uninstall-test",
            hostname="windows-test",
            os_name="windows",
            architecture="AMD64",
            address="192.0.2.90",
        )
        self.repo = AgentUninstallRepository(self.backend)

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_request_requires_exact_confirmation(self):
        with self.assertRaisesRegex(ValueError, "confirmation must exactly match agent_id"):
            self.repo.request(
                "agent-uninstall-test",
                mode="preserve-data",
                requested_by="admin",
                confirmation="wrong",
            )

    def test_typed_command_is_delivered_only_once(self):
        state = self.repo.request(
            "agent-uninstall-test",
            mode="preserve-data",
            requested_by="admin",
            confirmation="agent-uninstall-test",
        )
        self.assertEqual(state["status"], "queued")
        command = self.repo.command_for_agent("agent-uninstall-test")
        self.assertEqual(command["kind"], "AgentUninstallCommand")
        self.assertEqual(command["action"], "uninstall-agent")
        self.assertEqual(command["mode"], "preserve-data")
        self.assertEqual(command["request_id"], state["request_id"])
        self.assertIsNone(self.repo.command_for_agent("agent-uninstall-test"))
        self.assertEqual(self.repo.state("agent-uninstall-test")["status"], "delivered")

    def test_result_must_match_request_id(self):
        state = self.repo.request(
            "agent-uninstall-test",
            mode="preserve-data",
            requested_by="admin",
            confirmation="agent-uninstall-test",
        )
        self.repo.command_for_agent("agent-uninstall-test")
        self.assertIsNone(
            self.repo.apply_result(
                "agent-uninstall-test",
                {"request_id": "uninstall-other", "status": "completed"},
            )
        )
        completed = self.repo.apply_result(
            "agent-uninstall-test",
            {
                "request_id": state["request_id"],
                "status": "completed",
                "host_cleanup": {"task_removed": True, "runtime_removed": True},
            },
        )
        self.assertEqual(completed["status"], "completed")
        self.assertTrue(completed["host_cleanup"]["task_removed"])

    def test_purge_is_blocked_with_registered_instances(self):
        with self.backend.transaction() as connection:
            connection.execute(
                "INSERT INTO instances(id,node_id,game_id,name,status) VALUES (?,?,?,?,?)",
                ("instance-uninstall-test", "node-uninstall-test", "minecraft", "Test", "offline"),
            )
        with self.assertRaisesRegex(ValueError, "purge is blocked"):
            self.repo.request(
                "agent-uninstall-test",
                mode="purge",
                requested_by="admin",
                confirmation="agent-uninstall-test",
            )

    def test_preserve_data_can_be_requested_with_instances(self):
        with self.backend.transaction() as connection:
            connection.execute(
                "INSERT INTO instances(id,node_id,game_id,name,status) VALUES (?,?,?,?,?)",
                ("instance-preserve-test", "node-uninstall-test", "minecraft", "Test", "offline"),
            )
        state = self.repo.request(
            "agent-uninstall-test",
            mode="preserve-data",
            requested_by="admin",
            confirmation="agent-uninstall-test",
        )
        self.assertEqual(state["mode"], "preserve-data")


if __name__ == "__main__":
    unittest.main()
