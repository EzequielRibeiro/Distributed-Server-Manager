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
        self.controller_id = installation_profile_identity(
            RegistryRepository(self.backend),
            profile="controller",
            hostname="uninstall-controller",
        )["controller_id"]
        pairing = AgentPairingRepository(self.backend)
        token = pairing.issue_token(controller_id=self.controller_id, created_by="test")
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
        with self.backend.transaction() as connection:
            customer = connection.execute(
                "INSERT INTO customers(controller_id,name,status) VALUES (?,?,?)",
                (self.controller_id, "Uninstall Test Customer", "active"),
            )
            self.customer_id = int(customer.lastrowid)

        self.repo = AgentUninstallRepository(self.backend)

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def request(self, mode="preserve-data"):
        return self.repo.request(
            "agent-uninstall-test",
            mode=mode,
            requested_by="admin",
            confirmation="agent-uninstall-test",
        )

    def test_request_requires_exact_confirmation(self):
        with self.assertRaisesRegex(ValueError, "confirmation must exactly match agent_id"):
            self.repo.request(
                "agent-uninstall-test",
                mode="preserve-data",
                requested_by="admin",
                confirmation="wrong",
            )

    def test_prepare_then_commit_are_delivered_as_separate_typed_phases(self):
        state = self.request()
        prepare = self.repo.command_for_agent("agent-uninstall-test")
        self.assertEqual(prepare["kind"], "AgentUninstallCommand")
        self.assertEqual(prepare["phase"], "prepare")
        self.assertEqual(prepare["mode"], "preserve-data")
        self.assertEqual(prepare["request_id"], state["request_id"])
        self.assertIsNone(self.repo.command_for_agent("agent-uninstall-test"))
        self.assertEqual(self.repo.state("agent-uninstall-test")["status"], "delivered")

        accepted = self.repo.apply_result(
            "agent-uninstall-test",
            {"request_id": state["request_id"], "status": "accepted"},
        )
        self.assertEqual(accepted["status"], "accepted")
        commit = self.repo.command_for_agent("agent-uninstall-test")
        self.assertEqual(commit["phase"], "commit")
        self.assertEqual(commit["request_id"], state["request_id"])
        self.assertIsNone(self.repo.command_for_agent("agent-uninstall-test"))
        self.assertEqual(self.repo.state("agent-uninstall-test")["status"], "commit-delivered")

    def test_result_must_match_request_id_and_valid_transition(self):
        state = self.request()
        self.repo.command_for_agent("agent-uninstall-test")
        self.assertIsNone(
            self.repo.apply_result(
                "agent-uninstall-test",
                {"request_id": "uninstall-other", "status": "accepted"},
            )
        )
        self.assertIsNone(
            self.repo.apply_result(
                "agent-uninstall-test",
                {"request_id": state["request_id"], "status": "committed"},
            )
        )
        self.repo.apply_result(
            "agent-uninstall-test",
            {"request_id": state["request_id"], "status": "accepted"},
        )
        self.repo.command_for_agent("agent-uninstall-test")
        committed = self.repo.apply_result(
            "agent-uninstall-test",
            {"request_id": state["request_id"], "status": "committed"},
        )
        self.assertEqual(committed["status"], "committed")

    def test_purge_is_blocked_with_registered_instances(self):
        with self.backend.transaction() as connection:
            connection.execute(
                "INSERT INTO instances(id,node_id,game_id,name,status,controller_id,agent_id,customer_id) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    "instance-uninstall-test",
                    "node-uninstall-test",
                    "minecraft",
                    "Test",
                    "offline",
                    self.controller_id,
                    "agent-uninstall-test",
                    self.customer_id,
                ),
            )
        with self.assertRaisesRegex(ValueError, "purge is blocked"):
            self.request(mode="purge")

    def test_preserve_data_can_be_requested_with_instances(self):
        with self.backend.transaction() as connection:
            connection.execute(
                "INSERT INTO instances(id,node_id,game_id,name,status,controller_id,agent_id,customer_id) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    "instance-preserve-test",
                    "node-uninstall-test",
                    "minecraft",
                    "Test",
                    "offline",
                    self.controller_id,
                    "agent-uninstall-test",
                    self.customer_id,
                ),
            )
        state = self.request()
        self.assertEqual(state["mode"], "preserve-data")


if __name__ == "__main__":
    unittest.main()
