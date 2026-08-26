#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "database"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from agent_lifecycle_repository import AgentLifecycleRepository
from agent_link_incident_repository import AgentLinkIncidentRepository
from agent_link_monitor import AgentLinkMonitor
from agent_pairing_repository import AgentPairingRepository
from alert_repository import AlertSession, dialect_for_backend
from backend import DatabaseConfig
from backend_factory import create_backend
from registry import installation_profile_identity
from registry_repository import RegistryRepository
from universal_event_repository import UniversalEventRepository


class AgentLinkMonitorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(
            DatabaseConfig(driver="sqlite", database=str(Path(self.temp.name) / "capivara.db"))
        )
        identity = installation_profile_identity(
            RegistryRepository(self.backend), profile="controller", hostname="link-monitor-controller"
        )
        self.controller_id = str(identity["controller_id"])
        self.pairing = AgentPairingRepository(self.backend)
        self.now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def _agent(self, suffix: str, *, active: bool = True, age_seconds: int = 30) -> str:
        token = self.pairing.issue_token(controller_id=self.controller_id, created_by="test")
        agent_id = f"agent-monitor-{suffix}"
        self.pairing.enroll(
            pairing_token=token.token,
            agent_id=agent_id,
            node_id=f"node-monitor-{suffix}",
            name=f"Agent {suffix}",
            fingerprint=f"sha256:{suffix}",
            hostname=f"host-{suffix}",
            os_name="linux",
            architecture="x86_64",
        )
        if active:
            AgentLifecycleRepository(self.backend).transition(agent_id, "active")
        dialect = dialect_for_backend(self.backend)
        last_seen = (self.now - timedelta(seconds=age_seconds)).isoformat().replace("+00:00", "Z")
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                session.execute(
                    "UPDATE agent_runtime_inventory SET last_seen={0},degraded_after_seconds={0},"
                    "offline_after_seconds={0},health_status={0} WHERE agent_id={0}".format(dialect.placeholder),
                    (last_seen, 60, 120, "online", agent_id),
                )
            finally:
                session.close()
        return agent_id

    def test_stale_active_agent_opens_one_incident_and_deduplicates(self):
        agent_id = self._agent("stale", age_seconds=180)
        monitor = AgentLinkMonitor(self.backend)
        first = monitor.sweep(now=self.now)
        second = monitor.sweep(now=self.now)
        self.assertEqual(first["opened"], [agent_id])
        self.assertEqual(second["unchanged"], [agent_id])
        incident = AgentLinkIncidentRepository(self.backend).active(agent_id)
        self.assertIsNotNone(incident)
        events = UniversalEventRepository(self.backend).list_events(
            agent_id=agent_id, event_type="AGENT_LINK_LOST", limit=10
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["data"]["cause"], "heartbeat_expired")

    def test_recent_active_agent_does_not_open_incident(self):
        agent_id = self._agent("recent", age_seconds=30)
        result = AgentLinkMonitor(self.backend).sweep(now=self.now)
        self.assertNotIn(agent_id, result["opened"])
        self.assertIsNone(AgentLinkIncidentRepository(self.backend).active(agent_id))

    def test_pairing_agent_is_ignored_even_when_runtime_health_is_offline(self):
        agent_id = self._agent("pairing", active=False, age_seconds=180)
        result = AgentLinkMonitor(self.backend).sweep(now=self.now)
        self.assertIn(agent_id, result["skipped"])
        self.assertIsNone(AgentLinkIncidentRepository(self.backend).active(agent_id))


if __name__ == "__main__":
    unittest.main()
