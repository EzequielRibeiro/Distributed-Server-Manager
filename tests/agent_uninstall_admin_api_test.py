#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "database", ROOT / "dashboard"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from agent_pairing_repository import AgentPairingRepository
from agent_uninstall_admin_api import (
    agent_uninstall_state,
    force_remove_controller_registration,
    request_agent_uninstall,
)
from backend import DatabaseConfig
from backend_factory import create_backend
from registry import installation_profile_identity
from registry_repository import RegistryRepository


class AgentUninstallAdminApiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(DatabaseConfig(driver="sqlite", database=str(Path(self.temp.name) / "capivara.db")))
        controller_id = installation_profile_identity(
            RegistryRepository(self.backend),
            profile="controller",
            hostname="uninstall-admin-controller",
        )["controller_id"]
        pairing = AgentPairingRepository(self.backend)
        token = pairing.issue_token(controller_id=controller_id, created_by="test")
        pairing.enroll(
            pairing_token=token.token,
            agent_id="agent-admin-uninstall",
            node_id="node-admin-uninstall",
            name="Windows Agent",
            fingerprint="sha256:admin-uninstall",
            hostname="windows-admin-uninstall",
            os_name="windows",
            architecture="AMD64",
            address="192.0.2.91",
        )

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_remote_uninstall_retains_controller_registration(self):
        result = request_agent_uninstall(
            self.backend,
            agent_id="agent-admin-uninstall",
            mode="preserve-data",
            confirmation="agent-admin-uninstall",
            requested_by="admin",
        )
        self.assertTrue(result["remote_host_removal"])
        self.assertTrue(result["controller_registration_retained"])
        self.assertEqual(result["uninstall"]["status"], "queued")
        self.assertEqual(agent_uninstall_state(self.backend, agent_id="agent-admin-uninstall")["status"], "queued")

    def test_force_remove_is_explicitly_controller_only(self):
        result = force_remove_controller_registration(
            self.backend,
            agent_id="agent-admin-uninstall",
            confirmation="agent-admin-uninstall",
            removed_by="admin",
        )
        self.assertTrue(result["controller_only"])
        self.assertFalse(result["remote_host_removal"])
        self.assertIn("não foram desinstalados", result["warning"])


if __name__ == "__main__":
    unittest.main()
