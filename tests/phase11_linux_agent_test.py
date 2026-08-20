#!/usr/bin/env python3

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "database", ROOT / "dashboard"):
    sys.path.insert(0, str(path))

from backend import DatabaseConfig
from backend_factory import create_backend
from agent_install_command import linux_agent_install_command
from agent_pairing_repository import AgentPairingRepository
from agent_remote_http import dispatch_enroll, dispatch_heartbeat
from registry_repository import RegistryRepository


class Phase11LinuxAgentTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(
            DatabaseConfig(driver="sqlite", database=str(Path(self.temp.name) / "capivara.db"))
        )
        self.backend.initialize()
        RegistryRepository(self.backend).bootstrap_installation_profile(
            profile="controller",
            installation_id="controller-phase11",
            name="Controller Phase 11",
        )
        with self.backend.connect() as connection:
            row = connection.execute("SELECT id FROM controllers LIMIT 1").fetchone()
            self.controller_id = str(row["id"])

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_command_contains_only_controller_and_pairing_material(self):
        command = linux_agent_install_command(
            controller_url="https://controller.example",
            pairing_token="cap_pair_example",
        )
        self.assertIn("https://controller.example/agent/install.sh", command)
        self.assertIn("--controller-url https://controller.example", command)
        self.assertIn("--pairing-token cap_pair_example", command)
        self.assertNotIn("password", command.lower())
        self.assertNotIn("admin", command.lower())

    def test_enroll_then_first_authenticated_heartbeat_becomes_active(self):
        issued = AgentPairingRepository(self.backend).issue_token(
            controller_id=self.controller_id,
            ttl_seconds=300,
        )
        status, enrolled = dispatch_enroll(
            {
                "pairing_token": issued.token,
                "agent_id": "agent-linux-01",
                "node_id": "node-linux-01",
                "name": "Linux Agent 01",
                "fingerprint": "sha256:test-fingerprint",
                "hostname": "linux01",
                "os": "linux",
                "architecture": "x86_64",
            },
            backend=self.backend,
        )
        self.assertEqual(status, 201)
        self.assertEqual(enrolled["status"], "pairing")

        status, heartbeat = dispatch_heartbeat(
            {"agent_id": "agent-linux-01", "hostname": "linux01"},
            headers={
                "X-Capivara-Agent-Credential": enrolled["credential_id"],
                "X-Capivara-Agent-Secret": enrolled["credential_secret"],
                "X-Capivara-Agent-Fingerprint": "sha256:test-fingerprint",
            },
            backend=self.backend,
        )
        self.assertEqual(status, 200)
        self.assertEqual(heartbeat["health_status"], "online")
        self.assertEqual(heartbeat["status"], "active")

        with self.backend.connect() as connection:
            row = connection.execute(
                "SELECT status FROM agents WHERE id='agent-linux-01'"
            ).fetchone()
        self.assertEqual(row["status"], "active")


if __name__ == "__main__":
    unittest.main()
