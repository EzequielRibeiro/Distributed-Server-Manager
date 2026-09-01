#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

for item in (
    ROOT,
    ROOT / "dashboard",
    ROOT / "database",
):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from agent_remote_http import dispatch_uninstall_result
from agent_pairing_repository import AgentPairingRepository
from agent_uninstall_repository import AgentUninstallRepository
from backend import DatabaseConfig
from backend_factory import create_backend
from registry import installation_profile_identity
from registry_repository import RegistryRepository


class AgentUninstallTerminalHttpTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()

        self.backend = create_backend(
            DatabaseConfig(
                driver="sqlite",
                database=str(
                    Path(self.temp.name) / "capivara.db"
                ),
            )
        )

        self.controller_id = installation_profile_identity(
            RegistryRepository(self.backend),
            profile="controller",
            hostname="terminal-controller",
        )["controller_id"]

        pairing = AgentPairingRepository(self.backend)

        token = pairing.issue_token(
            controller_id=self.controller_id,
            created_by="test",
        )

        enrolled = pairing.enroll(
            pairing_token=token.token,
            agent_id="agent-terminal-test",
            node_id="node-terminal-test",
            name="Windows Agent",
            fingerprint="sha256:terminal-test",
            hostname="windows-terminal-test",
            os_name="windows",
            architecture="AMD64",
            address="192.0.2.91",
        )

        self.headers = {
            "X-Capivara-Agent-Credential":
                enrolled.credential_id,
            "X-Capivara-Agent-Secret":
                enrolled.credential_secret,
            "X-Capivara-Agent-Fingerprint":
                "sha256:terminal-test",
        }

        self.repo = AgentUninstallRepository(self.backend)

        state = self.repo.request(
            "agent-terminal-test",
            mode="preserve-data",
            requested_by="admin",
            confirmation="agent-terminal-test",
        )

        self.request_id = state["request_id"]

        self.repo.command_for_agent(
            "agent-terminal-test"
        )

        self.repo.apply_result(
            "agent-terminal-test",
            {
                "request_id": self.request_id,
                "status": "accepted",
            },
        )

        self.repo.command_for_agent(
            "agent-terminal-test"
        )

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_completed_is_accepted_without_heartbeat(self):
        status, body = dispatch_uninstall_result(
            {
                "request_id": self.request_id,
                "status": "completed",
                "host_cleanup": {
                    "install_root_removed": True,
                    "instances_preserved": True,
                    "backups_preserved": True,
                },
            },
            headers=self.headers,
            backend=self.backend,
        )

        self.assertEqual(status, 200)

        self.assertEqual(
            body["uninstall_state"]["status"],
            "completed",
        )

        self.assertEqual(
            self.repo.state(
                "agent-terminal-test"
            )["status"],
            "completed",
        )

    def test_invalid_secret_is_rejected(self):
        headers = dict(self.headers)
        headers["X-Capivara-Agent-Secret"] = "wrong"

        status, body = dispatch_uninstall_result(
            {
                "request_id": self.request_id,
                "status": "completed",
            },
            headers=headers,
            backend=self.backend,
        )

        self.assertEqual(status, 401)
        self.assertEqual(
            body["error"],
            "agent_authentication_failed",
        )

    def test_claimed_agent_must_match_authenticated_identity(self):
        status, body = dispatch_uninstall_result(
            {
                "agent_id": "agent-other",
                "request_id": self.request_id,
                "status": "completed",
            },
            headers=self.headers,
            backend=self.backend,
        )

        self.assertEqual(status, 409)
        self.assertEqual(
            body["error"],
            "agent_identity_mismatch",
        )

    def test_wrong_request_is_rejected(self):
        status, body = dispatch_uninstall_result(
            {
                "request_id": "uninstall-other",
                "status": "completed",
            },
            headers=self.headers,
            backend=self.backend,
        )

        self.assertEqual(status, 409)
        self.assertEqual(
            body["error"],
            "uninstall_result_rejected",
        )


if __name__ == "__main__":
    unittest.main()
