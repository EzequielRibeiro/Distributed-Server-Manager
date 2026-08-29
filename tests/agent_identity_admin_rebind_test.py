#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "database", ROOT / "dashboard"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from agent_identity_admin_repository import AgentIdentityAdminRepository, AgentIdentityRebindConflict
from agent_identity_incident_repository import AgentIdentityIncidentRepository
from agent_pairing_repository import AgentPairingRepository
from backend import DatabaseConfig
from backend_factory import create_backend
from registry import installation_profile_identity
from registry_repository import RegistryRepository

OLD = "sha256:" + "1" * 64
NEW = "sha256:" + "2" * 64
OTHER = "sha256:" + "3" * 64


class AgentIdentityAdminRebindTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(
            DatabaseConfig(driver="sqlite", database=str(Path(self.temp.name) / "capivara.db"))
        )
        identity = installation_profile_identity(
            RegistryRepository(self.backend),
            profile="controller",
            hostname="identity-admin-controller",
        )
        self.controller_id = str(identity["controller_id"])
        self.pairing = AgentPairingRepository(self.backend)
        token = self.pairing.issue_token(controller_id=self.controller_id, created_by="test")
        self.agent_id = "agent-identity-admin-test"
        self.node_id = "node-identity-admin-test"
        self.fingerprint = "sha256:identity-admin-test"
        self.enrolled = self.pairing.enroll(
            pairing_token=token.token,
            agent_id=self.agent_id,
            node_id=self.node_id,
            name="Identity Admin Agent",
            fingerprint=self.fingerprint,
            hostname="identity-host",
            os_name="linux",
            architecture="x86_64",
            address="192.0.2.40",
        )
        with self.backend.transaction() as connection:
            connection.execute(
                "UPDATE agents SET metadata_json=? WHERE id=?",
                (json.dumps({"capivara_host_identity_v1": OLD}), self.agent_id),
            )
        AgentIdentityIncidentRepository(self.backend).open_collision(
            self.agent_id,
            expected_identity=OLD,
            presented_identity=NEW,
        )
        self.repo = AgentIdentityAdminRepository(self.backend)

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_rebind_preserves_logical_identity_and_credential(self):
        before = self.pairing.authenticate(
            credential_id=self.enrolled.credential_id,
            credential_secret=self.enrolled.credential_secret,
            fingerprint=self.fingerprint,
        )
        result = self.repo.rebind(
            self.agent_id,
            expected_identity=OLD,
            new_identity=NEW,
            reason="controlled host replacement",
            actor="admin",
        )
        after = self.pairing.authenticate(
            credential_id=self.enrolled.credential_id,
            credential_secret=self.enrolled.credential_secret,
            fingerprint=self.fingerprint,
        )
        shown = self.repo.show(self.agent_id)

        self.assertEqual(result["old_identity"], OLD)
        self.assertEqual(result["new_identity"], NEW)
        self.assertTrue(result["incident_resolved"])
        self.assertEqual(shown["host_identity"], NEW)
        self.assertIsNone(shown["active_incident"])
        self.assertEqual(before["agent_id"], self.agent_id)
        self.assertEqual(after["agent_id"], self.agent_id)
        self.assertEqual(after["node_id"], self.node_id)
        self.assertEqual(after["credential_id"], self.enrolled.credential_id)

    def test_rebind_rejects_stale_expected_identity(self):
        with self.assertRaises(AgentIdentityRebindConflict):
            self.repo.rebind(
                self.agent_id,
                expected_identity=OTHER,
                new_identity=NEW,
                reason="stale request",
                actor="admin",
            )
        self.assertEqual(self.repo.show(self.agent_id)["host_identity"], OLD)

    def test_rebind_rejects_identity_bound_to_another_agent(self):
        token = self.pairing.issue_token(controller_id=self.controller_id, created_by="test")
        other_agent = "agent-identity-other"
        self.pairing.enroll(
            pairing_token=token.token,
            agent_id=other_agent,
            node_id="node-identity-other",
            name="Other Agent",
            fingerprint="sha256:identity-other",
            hostname="other-host",
            os_name="linux",
            architecture="x86_64",
            address="192.0.2.41",
        )
        with self.backend.transaction() as connection:
            connection.execute(
                "UPDATE agents SET metadata_json=? WHERE id=?",
                (json.dumps({"capivara_host_identity_v1": NEW}), other_agent),
            )

        with self.assertRaises(AgentIdentityRebindConflict):
            self.repo.rebind(
                self.agent_id,
                expected_identity=OLD,
                new_identity=NEW,
                reason="should conflict",
                actor="admin",
            )
        self.assertEqual(self.repo.show(self.agent_id)["host_identity"], OLD)

    def test_rebind_requires_reason_and_valid_hashes(self):
        with self.assertRaises(ValueError):
            self.repo.rebind(
                self.agent_id,
                expected_identity=OLD,
                new_identity="not-a-hash",
                reason="invalid",
                actor="admin",
            )
        with self.assertRaises(ValueError):
            self.repo.rebind(
                self.agent_id,
                expected_identity=OLD,
                new_identity=NEW,
                reason="",
                actor="admin",
            )


if __name__ == "__main__":
    unittest.main()
