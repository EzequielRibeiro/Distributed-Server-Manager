#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "database", ROOT / "dashboard", ROOT / "agents" / "linux" / "runtime"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from agent_admin_repository import AgentAdminRepository
from agent_pairing_repository import AgentCredentialInvalid, AgentPairingRepository
from agent_relink_repository import AgentRelinkRepository
from backend import DatabaseConfig
from backend_factory import create_backend
from registry import installation_profile_identity
from registry_repository import RegistryRepository


class AgentAdminMaintenanceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(
            DatabaseConfig(driver="sqlite", database=str(Path(self.temp.name) / "capivara.db"))
        )
        identity = installation_profile_identity(
            RegistryRepository(self.backend),
            profile="controller",
            hostname="agent-admin-controller",
        )
        self.controller_id = str(identity["controller_id"])
        self.pairing = AgentPairingRepository(self.backend)
        issued = self.pairing.issue_token(controller_id=self.controller_id, created_by="test")
        self.agent_id = "agent-admin-test"
        self.node_id = "node-admin-test"
        self.fingerprint = "sha256:agent-admin-test"
        self.enrolled = self.pairing.enroll(
            pairing_token=issued.token,
            agent_id=self.agent_id,
            node_id=self.node_id,
            name="Agent Original",
            fingerprint=self.fingerprint,
            hostname="agent-host",
            os_name="linux",
            architecture="x86_64",
            address="192.0.2.10",
        )
        self.admin = AgentAdminRepository(self.backend)

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def _prepared_relink_token(self):
        token = self.pairing.issue_token(
            controller_id=self.controller_id,
            created_by="admin",
        )
        self.admin.record_relink_prepared(
            self.agent_id,
            token_id=token.token_id,
            expires_at=token.expires_at,
            actor="admin",
        )
        return token

    def test_rename_changes_administrative_name_without_identity(self):
        result = self.admin.rename(self.agent_id, "Agent Produção", actor="admin")
        detail = self.admin.detail(self.agent_id)
        self.assertTrue(result["updated"])
        self.assertEqual(detail["name"], "Agent Produção")
        self.assertEqual(detail["agent_id"], self.agent_id)
        self.assertEqual(detail["node_id"], self.node_id)
        self.assertEqual(detail["hostname"], "agent-host")
        self.assertEqual(detail["fingerprint"], self.fingerprint)

    def test_doctor_request_delivery_and_result_are_persisted(self):
        queued = self.admin.request_doctor(self.agent_id, requested_by="admin")
        self.assertEqual(queued["status"], "queued")
        command = self.admin.doctor_command_for_agent(self.agent_id)
        self.assertEqual(command["request_id"], queued["request_id"])
        self.assertEqual(command["action"], "doctor")
        report = {
            "request_id": queued["request_id"],
            "status": "completed",
            "completed_at": "2026-08-26T03:30:00Z",
            "result": {
                "kind": "CapivaraAgentDoctor",
                "status": "healthy",
                "ready": True,
                "findings": [],
            },
        }
        state = self.admin.apply_doctor_result(self.agent_id, report)
        self.assertEqual(state["status"], "completed")
        self.assertEqual(self.admin.latest_doctor(self.agent_id)["result"]["status"], "healthy")
        self.assertIsNone(self.admin.doctor_command_for_agent(self.agent_id))

    def test_relink_rotates_credential_and_preserves_agent_identity(self):
        token = self._prepared_relink_token()
        recovered = AgentRelinkRepository(self.backend).relink(
            pairing_token=token.token,
            agent_id=self.agent_id,
            node_id=self.node_id,
            fingerprint=self.fingerprint,
        )
        self.assertEqual(recovered.agent_id, self.agent_id)
        self.assertEqual(recovered.node_id, self.node_id)
        self.assertEqual(recovered.fingerprint, self.fingerprint)
        self.assertNotEqual(recovered.credential_id, self.enrolled.credential_id)
        with self.assertRaises(AgentCredentialInvalid):
            self.pairing.authenticate(
                credential_id=self.enrolled.credential_id,
                credential_secret=self.enrolled.credential_secret,
                fingerprint=self.fingerprint,
            )
        authenticated = self.pairing.authenticate(
            credential_id=recovered.credential_id,
            credential_secret=recovered.credential_secret,
            fingerprint=self.fingerprint,
        )
        self.assertEqual(authenticated["agent_id"], self.agent_id)

    def test_relink_rejects_fingerprint_change(self):
        token = self._prepared_relink_token()
        with self.assertRaises(AgentCredentialInvalid):
            AgentRelinkRepository(self.backend).relink(
                pairing_token=token.token,
                agent_id=self.agent_id,
                node_id=self.node_id,
                fingerprint="sha256:different-host",
            )


if __name__ == "__main__":
    unittest.main()
