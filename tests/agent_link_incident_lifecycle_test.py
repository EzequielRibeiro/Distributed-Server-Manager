#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "database", ROOT / "dashboard"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from agent_link_incident_repository import AgentLinkIncidentRepository
from agent_pairing_repository import AgentPairingRepository
from agent_remote_http import dispatch_heartbeat
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
        self.fingerprint = "sha256:link-test"
        self.enrolled = pairing.enroll(
            pairing_token=token.token,
            agent_id=self.agent_id,
            node_id="node-link-test",
            name="Agent Link Test",
            fingerprint=self.fingerprint,
            hostname="link-host",
            os_name="linux",
            architecture="x86_64",
            address="192.0.2.40",
        )
        self.incidents = AgentLinkIncidentRepository(self.backend)

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def headers(self, *, secret=None, fingerprint=None):
        return {
            "X-Capivara-Agent-Credential": self.enrolled.credential_id,
            "X-Capivara-Agent-Secret": self.enrolled.credential_secret if secret is None else secret,
            "X-Capivara-Agent-Fingerprint": self.fingerprint if fingerprint is None else fingerprint,
        }

    def heartbeat_body(self, **extra):
        body = {
            "agent_id": self.agent_id,
            "hostname": "link-host",
            "os": "linux",
            "architecture": "x86_64",
            "capivara_version": "2.0.0",
            "fingerprint": self.fingerprint,
            "heartbeat_interval_seconds": 30,
            "degraded_after_seconds": 60,
            "offline_after_seconds": 120,
        }
        body.update(extra)
        return body

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

    def test_bad_known_credential_opens_incident_and_good_heartbeat_requests_doctor(self):
        status, response = dispatch_heartbeat(
            self.heartbeat_body(),
            headers=self.headers(secret="wrong-secret"),
            backend=self.backend,
        )
        self.assertEqual(status, 401)
        self.assertEqual(response["error"], "agent_authentication_failed")
        incident = self.incidents.active(self.agent_id)
        self.assertIsNotNone(incident)

        status, response = dispatch_heartbeat(
            self.heartbeat_body(),
            headers=self.headers(),
            backend=self.backend,
        )
        self.assertEqual(status, 200)
        self.assertEqual(response["link_incident"]["status"], "recovering")
        self.assertEqual(response["doctor_command"]["action"], "doctor")
        self.assertIsNotNone(self.incidents.active(self.agent_id))

    def test_healthy_doctor_result_resolves_incident_after_authenticated_heartbeat(self):
        self.incidents.open(
            self.agent_id,
            cause="credential_invalid",
            recommended_action="Revincular Agent",
        )
        status, first = dispatch_heartbeat(
            self.heartbeat_body(),
            headers=self.headers(),
            backend=self.backend,
        )
        self.assertEqual(status, 200)
        request_id = first["doctor_command"]["request_id"]

        status, second = dispatch_heartbeat(
            self.heartbeat_body(
                doctor_result={
                    "request_id": request_id,
                    "status": "completed",
                    "completed_at": "2026-08-26T05:00:00Z",
                    "result": {
                        "kind": "CapivaraAgentDoctor",
                        "status": "healthy",
                        "ready": True,
                        "findings": [],
                    },
                }
            ),
            headers=self.headers(),
            backend=self.backend,
        )
        self.assertEqual(status, 200)
        self.assertEqual(second["link_incident"]["status"], "resolved")
        self.assertIsNone(self.incidents.active(self.agent_id))

    def test_spoofed_fingerprint_does_not_attribute_auth_failure(self):
        status, _ = dispatch_heartbeat(
            self.heartbeat_body(),
            headers=self.headers(secret="wrong-secret", fingerprint="sha256:other-host"),
            backend=self.backend,
        )
        self.assertEqual(status, 401)
        self.assertIsNone(self.incidents.active(self.agent_id))


if __name__ == "__main__":
    unittest.main()
