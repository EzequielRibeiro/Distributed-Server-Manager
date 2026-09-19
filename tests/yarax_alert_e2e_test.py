#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "database", ROOT / "monitor"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from alert_repository import AlertRepository
from agent_runtime_repository import AgentRuntimeRepository
from backend import DatabaseConfig
from backend_factory import create_backend
from universal_event_repository import UniversalEventRepository
from alert_engine import DatabaseAlertEngine


class YaraXAlertE2ETest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        database = Path(self.temp.name) / "capivara.db"
        self.backend = create_backend(DatabaseConfig(driver="sqlite", database=str(database)))
        self.backend.initialize()
        self.alerts = AlertRepository(self.backend)
        self.events = UniversalEventRepository(self.backend)
        self.runtime = AgentRuntimeRepository(self.backend)
        self.engine = DatabaseAlertEngine(self.backend)
        self._seed_topology()
        self.engine.initialize()
        self.engine._initialize_cursor()

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def _seed_topology(self):
        with self.backend.transaction() as connection:
            connection.execute(
                "INSERT INTO nodes(id,name,role,status) VALUES (?,?,?,?)",
                ("controller-node", "Controller", "controller", "active"),
            )
            connection.execute(
                "INSERT INTO controllers(id,node_id,name,status) VALUES (?,?,?,?)",
                ("controller-a", "controller-node", "Controller A", "active"),
            )
            connection.execute(
                "INSERT INTO nodes(id,name,role,status) VALUES (?,?,?,?)",
                ("agent-node", "Agent", "agent", "active"),
            )
            connection.execute(
                "INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?)",
                ("agent-a", "controller-a", "agent-node", "Agent A", "active"),
            )
            connection.execute(
                "INSERT INTO customers(id,controller_id,name,status) VALUES (?,?,?,?)",
                ("customer-a", "controller-a", "Customer A", "active"),
            )
            connection.execute(
                "INSERT INTO instances(id,controller_id,agent_id,customer_id,node_id,game_id,name,status) VALUES (?,?,?,?,?,?,?,?)",
                ("instance-a", "controller-a", "agent-a", "customer-a", "agent-node", "dayz", "Instance A", "active"),
            )

    def _publish_scan(self, result: str, *, severity: str):
        event_type = "YARAX_SCAN_FAILED" if result == "scan_failed" else "YARAX_SCAN_COMPLETED"
        return self.events.publish(
            {
                "event_type": event_type,
                "source": "agent.runtime",
                "source_id": "agent-a",
                "severity": severity,
                "agent_id": "agent-a",
                "instance_id": "instance-a",
                "data": {
                    "result": result,
                    "content_id": "steam-workshop:1828439124",
                    "engine_version": "1.20.0",
                    "ruleset_version": "2026.09.18.1",
                    "matches": (
                        [{"rule": "Capivara_EICAR_Test_File", "tags": ["block", "malware", "test"]}]
                        if result == "blocked"
                        else []
                    ),
                    "error": "scanner unavailable" if result == "scan_failed" else None,
                },
            }
        )

    def _active_rule(self, rule_id: str):
        rows = self.alerts.list_alerts(active_only=True, rule_id=rule_id)
        return rows[0] if rows else None

    def test_blocked_event_persists_opens_critical_and_clean_resolves(self):
        stored = self._publish_scan("blocked", severity="critical")
        self.assertTrue(stored["created"])
        self.assertEqual(stored["event"]["event_type"], "YARAX_SCAN_COMPLETED")

        self.engine.cycle()
        alert = self._active_rule("YARAX_CONTENT_BLOCKED")
        self.assertIsNotNone(alert)
        self.assertEqual(alert["level"], "CRITICAL")
        self.assertEqual(alert["scope"], "instance")
        self.assertEqual(alert["instance_id"], "instance-a")

        self._publish_scan("clean", severity="info")
        self.engine.cycle()
        self.assertIsNone(self._active_rule("YARAX_CONTENT_BLOCKED"))
        history = self.alerts.list_alerts(rule_id="YARAX_CONTENT_BLOCKED")
        self.assertEqual(history[0]["state"], "RESOLVED")

    def test_suspicious_and_scan_failed_are_distinct_warning_alerts(self):
        self._publish_scan("suspicious", severity="warning")
        self.engine.cycle()
        suspicious = self._active_rule("YARAX_CONTENT_SUSPICIOUS")
        self.assertIsNotNone(suspicious)
        self.assertEqual(suspicious["level"], "WARNING")

        self._publish_scan("scan_failed", severity="warning")
        self.engine.cycle()
        failed = self._active_rule("YARAX_SCAN_FAILED")
        self.assertIsNotNone(failed)
        self.assertEqual(failed["level"], "WARNING")

        self._publish_scan("clean", severity="info")
        self.engine.cycle()
        self.assertIsNone(self._active_rule("YARAX_CONTENT_SUSPICIOUS"))
        self.assertIsNone(self._active_rule("YARAX_SCAN_FAILED"))

    def test_health_capabilities_open_and_resolve_missing_and_outdated_alerts(self):
        degraded = {
            "content_security": {
                "ready": False,
                "state": "missing_engine",
                "engine_state": "missing",
                "rules_state": "missing",
                "engine_version": None,
                "engine_pinned_version": "1.20.0",
                "ruleset_version": None,
                "ruleset_pinned_version": "2026.09.18.1",
                "ruleset_checksum_valid": None,
                "last_error": "YARA-X engine is unavailable",
            }
        }
        self.runtime.upsert_inventory(agent_id="agent-a", capabilities=degraded)
        self.engine.evaluate_yarax_health()
        self.assertIsNotNone(self._active_rule("YARAX_ENGINE_UNAVAILABLE"))
        self.assertIsNotNone(self._active_rule("YARAX_RULESET_UNAVAILABLE"))

        outdated = {
            "content_security": {
                "ready": True,
                "state": "ready",
                "engine_state": "ready",
                "rules_state": "ready",
                "engine_version": "1.19.0",
                "engine_pinned_version": "1.20.0",
                "ruleset_version": "2026.09.17.1",
                "ruleset_pinned_version": "2026.09.18.1",
                "ruleset_checksum_valid": True,
            }
        }
        self.runtime.upsert_inventory(agent_id="agent-a", capabilities=outdated)
        self.engine.evaluate_yarax_health()
        self.assertIsNone(self._active_rule("YARAX_ENGINE_UNAVAILABLE"))
        self.assertIsNone(self._active_rule("YARAX_RULESET_UNAVAILABLE"))
        self.assertIsNotNone(self._active_rule("YARAX_ENGINE_OUTDATED"))
        self.assertIsNotNone(self._active_rule("YARAX_RULESET_OUTDATED"))

        ready = {
            "content_security": {
                "ready": True,
                "state": "ready",
                "engine_state": "ready",
                "rules_state": "ready",
                "engine_version": "1.20.0",
                "engine_pinned_version": "1.20.0",
                "ruleset_version": "2026.09.18.1",
                "ruleset_pinned_version": "2026.09.18.1",
                "ruleset_checksum_valid": True,
            }
        }
        self.runtime.upsert_inventory(agent_id="agent-a", capabilities=ready)
        self.engine.evaluate_yarax_health()
        for rule_id in (
            "YARAX_ENGINE_UNAVAILABLE",
            "YARAX_RULESET_UNAVAILABLE",
            "YARAX_ENGINE_OUTDATED",
            "YARAX_RULESET_OUTDATED",
        ):
            self.assertIsNone(self._active_rule(rule_id), rule_id)

    def test_health_alerts_are_deduped_per_agent(self):
        capabilities = {
            "content_security": {
                "ready": False,
                "state": "rules_error",
                "engine_state": "ready",
                "rules_state": "error",
                "engine_version": "1.20.0",
                "engine_pinned_version": "1.20.0",
                "ruleset_version": "2026.09.18.1",
                "ruleset_pinned_version": "2026.09.18.1",
                "ruleset_checksum_valid": False,
                "last_error": "ruleset checksum invalid",
            }
        }
        self.runtime.upsert_inventory(agent_id="agent-a", capabilities=capabilities)
        self.engine.evaluate_yarax_health()
        first = self._active_rule("YARAX_RULESET_UNAVAILABLE")
        self.engine.evaluate_yarax_health()
        second = self._active_rule("YARAX_RULESET_UNAVAILABLE")
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(self.alerts.list_alerts(active_only=True, rule_id="YARAX_RULESET_UNAVAILABLE")), 1)


if __name__ == "__main__":
    unittest.main()
