#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "database", ROOT / "dashboard"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from agent_lifecycle_repository import AgentLifecycleRepository
from agent_link_incident_repository import AgentLinkIncidentRepository
from agent_link_monitor import AgentLinkMonitor
from agent_pairing_repository import AgentPairingRepository
from agent_remote_http import dispatch_heartbeat
from alert_repository import AlertSession, dialect_for_backend
from backend import DatabaseConfig
from backend_factory import create_backend
from registry import installation_profile_identity
from registry_repository import RegistryRepository
from universal_event_repository import UniversalEventRepository


class AgentLinkRecoveryE2ETest(unittest.TestCase):
    """Exercise the complete Controller-side Agent link loss/recovery cycle."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(
            DatabaseConfig(driver="sqlite", database=str(Path(self.temp.name) / "capivara.db"))
        )
        identity = installation_profile_identity(
            RegistryRepository(self.backend),
            profile="controller",
            hostname="link-e2e-controller",
        )
        self.controller_id = str(identity["controller_id"])
        pairing = AgentPairingRepository(self.backend)
        token = pairing.issue_token(controller_id=self.controller_id, created_by="test")
        self.agent_id = "agent-link-e2e"
        self.fingerprint = "sha256:link-e2e"
        self.enrolled = pairing.enroll(
            pairing_token=token.token,
            agent_id=self.agent_id,
            node_id="node-link-e2e",
            name="Agent Link E2E",
            fingerprint=self.fingerprint,
            hostname="link-e2e-host",
            os_name="linux",
            architecture="x86_64",
            address="192.0.2.80",
        )
        AgentLifecycleRepository(self.backend).transition(self.agent_id, "active")
        self.incidents = AgentLinkIncidentRepository(self.backend)
        self.now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def headers(self):
        return {
            "X-Capivara-Agent-Credential": self.enrolled.credential_id,
            "X-Capivara-Agent-Secret": self.enrolled.credential_secret,
            "X-Capivara-Agent-Fingerprint": self.fingerprint,
        }

    def heartbeat_body(self, **extra):
        body = {
            "agent_id": self.agent_id,
            "hostname": "link-e2e-host",
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

    def set_last_seen(self, when: datetime):
        dialect = dialect_for_backend(self.backend)
        value = when.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                session.execute(
                    "UPDATE agent_runtime_inventory SET last_seen={0},degraded_after_seconds={0},"
                    "offline_after_seconds={0},health_status={0} WHERE agent_id={0}".format(
                        dialect.placeholder
                    ),
                    (value, 60, 120, "online", self.agent_id),
                )
            finally:
                session.close()

    def doctor_result(self, request_id: str, *, findings, status="critical"):
        return {
            "request_id": request_id,
            "status": "completed",
            "completed_at": "2026-08-26T12:05:00Z",
            "result": {
                "kind": "CapivaraAgentDoctor",
                "status": status,
                "ready": status != "critical",
                "findings": findings,
            },
        }

    def test_expiry_to_doctor_gated_recovery_and_recurrence(self):
        # 1. A stale operational Agent is detected by the periodic Controller sweep.
        self.set_last_seen(self.now - timedelta(seconds=180))
        first_sweep = AgentLinkMonitor(self.backend).sweep(now=self.now)
        self.assertEqual(first_sweep["opened"], [self.agent_id])
        first_incident = self.incidents.active(self.agent_id)
        self.assertIsNotNone(first_incident)
        first_id = first_incident["id"]

        # 2. Repeated sweeps deduplicate the same logical outage.
        repeated = AgentLinkMonitor(self.backend).sweep(now=self.now)
        self.assertEqual(repeated["unchanged"], [self.agent_id])
        self.assertEqual(self.incidents.active(self.agent_id)["id"], first_id)

        # 3. An authenticated heartbeat starts recovery and requests typed Doctor.
        http_status, recovery = dispatch_heartbeat(
            self.heartbeat_body(), headers=self.headers(), backend=self.backend
        )
        self.assertEqual(http_status, 200)
        self.assertEqual(recovery["link_incident"]["status"], "recovering")
        self.assertEqual(recovery["link_incident"]["incident_id"], first_id)
        doctor_request_id = recovery["doctor_command"]["request_id"]

        # 4. A critical link/identity Doctor finding MUST keep the incident open.
        http_status, blocked = dispatch_heartbeat(
            self.heartbeat_body(
                doctor_result=self.doctor_result(
                    doctor_request_id,
                    findings=[
                        {
                            "severity": "critical",
                            "code": "fingerprint_mismatch",
                            "message": "Agent fingerprint differs from the trusted identity.",
                        }
                    ],
                )
            ),
            headers=self.headers(),
            backend=self.backend,
        )
        self.assertEqual(http_status, 200)
        self.assertEqual(blocked["link_incident"]["status"], "recovering")
        self.assertEqual(self.incidents.active(self.agent_id)["id"], first_id)

        # The blocked recovery queues/retains a Doctor command. Complete that Doctor
        # without a critical identity/link finding to confirm objective recovery.
        healthy_request_id = blocked["doctor_command"]["request_id"]
        http_status, restored = dispatch_heartbeat(
            self.heartbeat_body(
                doctor_result=self.doctor_result(
                    healthy_request_id,
                    status="degraded",
                    findings=[
                        {
                            "severity": "warning",
                            "code": "low_disk_space",
                            "message": "Disk space is low but Agent identity is valid.",
                        }
                    ],
                )
            ),
            headers=self.headers(),
            backend=self.backend,
        )
        self.assertEqual(http_status, 200)
        self.assertEqual(restored["link_incident"]["status"], "resolved")
        self.assertEqual(restored["link_incident"]["incident_id"], first_id)
        self.assertIsNone(self.incidents.active(self.agent_id))

        # 5. History and paired lost/restored events remain available after recovery.
        history = self.incidents.history(self.agent_id)
        historical = next(item for item in history if item["id"] == first_id)
        self.assertEqual(historical["state"], "RESOLVED")
        events = UniversalEventRepository(self.backend).list_events(agent_id=self.agent_id, limit=20)
        first_events = [event for event in events if event.get("correlation_id") == first_id]
        self.assertEqual(
            {event["event_type"] for event in first_events},
            {"AGENT_LINK_LOST", "AGENT_LINK_RESTORED"},
        )

        # 6. A later independent outage creates a new logical incident.
        second_now = self.now + timedelta(minutes=10)
        self.set_last_seen(second_now - timedelta(seconds=180))
        second_sweep = AgentLinkMonitor(self.backend).sweep(now=second_now)
        self.assertEqual(second_sweep["opened"], [self.agent_id])
        second_incident = self.incidents.active(self.agent_id)
        self.assertIsNotNone(second_incident)
        self.assertNotEqual(second_incident["id"], first_id)


if __name__ == "__main__":
    unittest.main()
