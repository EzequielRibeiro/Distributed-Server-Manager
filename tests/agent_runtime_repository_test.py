#!/usr/bin/env python3

import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"
for path in (ROOT, DATABASE):
    sys.path.insert(0, str(path))

from backend import DatabaseConfig
from backend_factory import create_backend
from agent_runtime_repository import AgentRuntimeRepository
from alert_repository import AlertRepository
from registry_repository import RegistryRepository
from universal_event_repository import UniversalEventRepository


class AgentRuntimeRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp.name) / "capivara.db"
        self.backend = create_backend(
            DatabaseConfig(driver="sqlite", database=str(self.database_path))
        )
        self.backend.initialize()
        RegistryRepository(self.backend).bootstrap_topology(
            controller_id="controller-main",
            controller_node_id="controller-node",
            controller_name="Controller",
            agent_id="agent-main",
            agent_node_id="agent-node",
            agent_name="Agent",
        )
        self.runtime = AgentRuntimeRepository(self.backend)

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def agent_status(self):
        connection = sqlite3.connect(self.database_path)
        try:
            return connection.execute(
                "SELECT status FROM agents WHERE id='agent-main'"
            ).fetchone()[0]
        finally:
            connection.close()

    def test_inventory_contains_required_agent_facts_and_port_ranges(self):
        self.runtime.upsert_inventory(
            agent_id="agent-main",
            hostname="horizon-server",
            os_name="Ubuntu 24.04",
            architecture="x86_64",
            capivara_version="1.4.3",
            address="192.0.2.10",
            fingerprint="sha256:test",
            capabilities={"games": ["dayz", "minecraft"], "steamcmd": True},
            cpu={"model": "Intel", "cores": 4},
            ram_total_bytes=17179869184,
            storage={"total_bytes": 500000000000, "free_bytes": 400000000000},
        )
        item = self.runtime.snapshot("agent-main")
        self.assertEqual(item["agent_id"], "agent-main")
        self.assertEqual(item["node_id"], "agent-node")
        self.assertEqual(item["controller_id"], "controller-main")
        self.assertEqual(item["hostname"], "horizon-server")
        self.assertEqual(item["os_name"], "Ubuntu 24.04")
        self.assertEqual(item["architecture"], "x86_64")
        self.assertEqual(item["capivara_version"], "1.4.3")
        self.assertEqual(item["address"], "192.0.2.10")
        self.assertEqual(item["fingerprint"], "sha256:test")
        self.assertTrue(item["capabilities"]["steamcmd"])
        self.assertEqual(item["cpu"]["cores"], 4)
        self.assertEqual(item["ram_total_bytes"], 17179869184)
        self.assertGreaterEqual(len(item["port_ranges"]), 2)

    def test_heartbeat_health_never_changes_administrative_status(self):
        now = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
        self.runtime.heartbeat("agent-main", observed_at=now)
        self.assertEqual(self.agent_status(), "active")
        self.assertEqual(self.runtime.snapshot("agent-main", now=now)["health_status"], "online")
        later = now + timedelta(seconds=70)
        self.assertEqual(self.runtime.snapshot("agent-main", now=later)["health_status"], "degraded")
        self.assertEqual(self.agent_status(), "active")
        much_later = now + timedelta(seconds=130)
        self.assertEqual(self.runtime.snapshot("agent-main", now=much_later)["health_status"], "offline")
        self.assertEqual(self.agent_status(), "active")

    def test_health_transitions_publish_event_alert_and_recovery(self):
        now = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
        self.runtime.heartbeat("agent-main", observed_at=now)

        degraded_at = now + timedelta(seconds=70)
        self.runtime.refresh_health(now=degraded_at)
        events = UniversalEventRepository(self.backend).list_events(agent_id="agent-main", limit=20)
        self.assertEqual(events[0]["event_type"], "AGENT_DEGRADED")
        self.assertEqual(events[0]["severity"], "warning")
        correlation_id = events[0]["correlation_id"]
        self.assertTrue(correlation_id.startswith("agent-health:agent-main:"))

        alert = AlertRepository(self.backend).get_alert("agent-health:agent-main")
        self.assertIsNotNone(alert)
        self.assertEqual(alert["state"], "OPEN")
        self.assertEqual(alert["level"], "WARNING")

        offline_at = now + timedelta(seconds=130)
        self.runtime.refresh_health(now=offline_at)
        events = UniversalEventRepository(self.backend).list_events(agent_id="agent-main", limit=20)
        self.assertEqual(events[0]["event_type"], "AGENT_OFFLINE")
        self.assertEqual(events[0]["severity"], "critical")
        self.assertEqual(events[0]["correlation_id"], correlation_id)
        alert = AlertRepository(self.backend).get_alert("agent-health:agent-main")
        self.assertEqual(alert["state"], "OPEN")
        self.assertEqual(alert["level"], "CRITICAL")

        count_before = len(events)
        self.runtime.refresh_health(now=offline_at + timedelta(seconds=30))
        events = UniversalEventRepository(self.backend).list_events(agent_id="agent-main", limit=20)
        self.assertEqual(len(events), count_before)

        recovered_at = offline_at + timedelta(seconds=31)
        self.runtime.heartbeat("agent-main", observed_at=recovered_at)
        events = UniversalEventRepository(self.backend).list_events(agent_id="agent-main", limit=20)
        self.assertEqual(events[0]["event_type"], "AGENT_RECOVERED")
        self.assertEqual(events[0]["correlation_id"], correlation_id)
        alert = AlertRepository(self.backend).get_alert("agent-health:agent-main")
        self.assertEqual(alert["state"], "RESOLVED")
        self.assertEqual(self.runtime.snapshot("agent-main", now=recovered_at)["health_status"], "online")


if __name__ == "__main__":
    unittest.main()
