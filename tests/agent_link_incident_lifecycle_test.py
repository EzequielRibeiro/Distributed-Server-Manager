#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "database"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from agent_link_incident_repository import AgentLinkIncidentRepository
from agent_pairing_repository import AgentPairingRepository
from backend import DatabaseConfig
from backend_factory import create_backend
from registry import installation_profile_identity
from registry_repository import RegistryRepository
from universal_event_repository import UniversalEventRepository


class AgentLinkIncidentLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(
            DatabaseConfig(driver="sqlite", database=str(Path(self.temp.name) / "capivara.db"))
        )
        identity = installation_profile_identity(
            RegistryRepository(self.backend),
            profile="controller",
            hostname="link-controller",
        )
        self.controller_id = str(identity["controller_id"])
        pairing = AgentPairingRepository(self.backend)
        token = pairing.issue_token(controller_id=self.controller_id, created_by="test")
        self.agent_id = "agent-link-test"
        pairing.enroll(
            pairing_token=token.token,
            agent_id=self.agent_id,
            node_id="node-link-test",
            name="Agent Link Test",
            fingerprint="sha256:link-test",
            hostname="link-host",
            os_name="linux",
            architecture="x86_64",
            address="192.0.2.40",
        )
        self.incidents = AgentLinkIncidentRepository(self.backend)

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_repeated_failure_keeps_one_active_incident(self):
        first = self.incidents.open(
            self.agent_id,
            cause="heartbeat_expired",
            recommended_action="Executar Doctor",
        )
        second = self.incidents.open(
            self.agent_id,
            cause="heartbeat_expired",
            recommended_action="Executar Doctor",
        )
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["action"], "UNCHANGED")
        active = self.incidents.active(self.agent_id)
        self.assertEqual(active["id"], first["id"])
        events = UniversalEventRepository(self.backend).list_events(
            agent_id=self.agent_id, event_type="AGENT_LINK_LOST", limit=10
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["correlation_id"], first["id"])

    def test_resolution_preserves_history_and_emits_restored_event(self):
        opened = self.incidents.open(
            self.agent_id,
            cause="credential_invalid",
            recommended_action="Revincular Agent",
        )
        resolved = self.incidents.resolve(
            self.agent_id,
            recovery="relink_completed",
            doctor_status="healthy",
        )
        self.assertEqual(resolved["state"], "RESOLVED")
        self.assertIsNone(self.incidents.active(self.agent_id))
        history = self.incidents.history(self.agent_id)
        self.assertEqual(history[0]["id"], opened["id"])
        self.assertEqual(history[0]["state"], "RESOLVED")
        events = UniversalEventRepository(self.backend).list_events(
            agent_id=self.agent_id, limit=10
        )
        types = {event["event_type"] for event in events}
        self.assertIn("AGENT_LINK_LOST", types)
        self.assertIn("AGENT_LINK_RESTORED", types)

    def test_new_failure_after_resolution_creates_new_occurrence(self):
        first = self.incidents.open(
            self.agent_id,
            cause="heartbeat_expired",
            recommended_action="Executar Doctor",
        )
        self.incidents.resolve(self.agent_id, doctor_status="healthy")
        second = self.incidents.open(
            self.agent_id,
            cause="heartbeat_expired",
            recommended_action="Executar Doctor",
        )
        self.assertNotEqual(first["id"], second["id"])
        history = self.incidents.history(self.agent_id)
        ids = {item["id"] for item in history}
        self.assertEqual(ids, {first["id"], second["id"]})


if __name__ == "__main__":
    unittest.main()
