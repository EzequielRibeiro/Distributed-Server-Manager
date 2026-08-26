#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "core", ROOT / "database", ROOT / "dashboard", ROOT / "monitor"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from activity_audit_repository import ActivityAuditRepository, sanitize_changes
from activity_humanizer import humanize
from agent_instance_provisioning_repository import AgentInstanceProvisioningRepository
from alert_engine import DatabaseAlertEngine
from alert_repository import AlertRepository
from backend import DatabaseConfig
from backend_factory import create_backend
from universal_event_repository import UniversalEventRepository


class DatabaseFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(DatabaseConfig(
            driver="sqlite",
            database=str(Path(self.temp.name) / "capivara.db"),
        ))
        self.backend.initialize()
        with self.backend.transaction() as connection:
            connection.execute("INSERT INTO nodes(id,name,role,status) VALUES (?,?,?,?)", ("controller-node", "Controller", "controller", "active"))
            connection.execute("INSERT INTO nodes(id,name,role,status) VALUES (?,?,?,?)", ("agent-node", "Agent", "agent", "active"))
            connection.execute("INSERT INTO controllers(id,node_id,name,status) VALUES (?,?,?,?)", ("controller-1", "controller-node", "Controller", "active"))
            connection.execute("INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?)", ("agent-1", "controller-1", "agent-node", "Agent", "active"))
            connection.execute("INSERT INTO customers(id,controller_id,name,status) VALUES (?,?,?,?)", (1, "controller-1", "Cliente Teste", "active"))
            connection.execute(
                "INSERT INTO instances(id,node_id,game_id,runtime_id,name,status,controller_id,agent_id,customer_id) VALUES (?,?,?,?,?,?,?,?,?)",
                ("instance-1", "agent-node", "minecraft", "minecraft.bedrock.vanilla", "Servidor Teste", "offline", "controller-1", "agent-1", 1),
            )

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()


class SemanticActivityAuditTest(DatabaseFixture):
    def test_records_human_readable_customer_change(self):
        changes = {"name": {"before": "Joao", "after": "João"}}
        summary = humanize(
            "customer.updated",
            user={"username": "fulano", "display_name": "Fulano"},
            target_name="João",
            changes=changes,
        )
        repo = ActivityAuditRepository(self.backend)
        activity_id = repo.record_action(
            actor_id="fulano",
            actor_name="Fulano",
            actor_role="admin",
            action="customer.updated",
            category="customers",
            target_type="customer",
            target_id="cli1",
            target_name="João",
            result="success",
            summary=summary,
            changes=changes,
        )
        rows = repo.search(actor_id="fulano")
        self.assertEqual(rows[0]["activity_id"], activity_id)
        self.assertIn("Fulano alterou o cadastro do cliente João", rows[0]["summary"])
        self.assertEqual(rows[0]["changes"]["name"]["before"], "Joao")
        self.assertEqual(rows[0]["changes"]["name"]["after"], "João")

    def test_sensitive_values_are_never_persisted_in_change_set(self):
        clean = sanitize_changes({
            "password": {"before": "old-secret", "after": "new-secret"},
            "api_token": {"before": "token-one", "after": "token-two"},
            "name": {"before": "A", "after": "B"},
        })
        self.assertEqual(clean["password"], {"changed": True})
        self.assertEqual(clean["api_token"], {"changed": True})
        self.assertEqual(clean["name"], {"before": "A", "after": "B"})
        serialized = str(clean)
        self.assertNotIn("old-secret", serialized)
        self.assertNotIn("token-one", serialized)


class DatabaseAlertEngineTest(DatabaseFixture):
    def test_critical_universal_event_opens_database_alert(self):
        events = UniversalEventRepository(self.backend)
        engine = DatabaseAlertEngine(self.backend)
        engine.cycle()
        events.publish({
            "event_id": "failure-event-1",
            "event_type": "INSTANCE_PROVISION_FAILED",
            "source": "controller.provisioning",
            "severity": "critical",
            "agent_id": "agent-1",
            "instance_id": "instance-1",
            "data": {"message": "Falha ao provisionar o servidor"},
        })
        self.assertEqual(engine.cycle(), 1)
        alerts = AlertRepository(self.backend).list_alerts(active_only=True, instance_id="instance-1")
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["level"], "CRITICAL")
        self.assertEqual(alerts[0]["rule_id"], "INSTANCE_PROVISION_FAILED")
        self.assertEqual(alerts[0]["message"], "Falha ao provisionar o servidor")

    def test_provision_completed_resolves_failure_and_steam_alerts(self):
        events = UniversalEventRepository(self.backend)
        engine = DatabaseAlertEngine(self.backend)
        engine.cycle()
        common = {
            "source": "controller.provisioning",
            "severity": "critical",
            "agent_id": "agent-1",
            "instance_id": "instance-1",
        }
        events.publish({
            **common,
            "event_id": "failure-event-2",
            "event_type": "INSTANCE_PROVISION_FAILED",
            "data": {"message": "Falha no provisionamento"},
        })
        events.publish({
            **common,
            "event_id": "steam-event-1",
            "event_type": "STEAM_AUTH_REQUIRED",
            "data": {"message": "Autenticação Steam necessária"},
        })
        self.assertEqual(engine.cycle(), 2)
        self.assertEqual(
            len(AlertRepository(self.backend).list_alerts(active_only=True, instance_id="instance-1")),
            2,
        )
        events.publish({
            "event_id": "completed-event-1",
            "event_type": "INSTANCE_PROVISION_COMPLETED",
            "source": "controller.provisioning",
            "severity": "info",
            "agent_id": "agent-1",
            "instance_id": "instance-1",
            "data": {"message": "Provisionamento concluído"},
        })
        self.assertEqual(engine.cycle(), 1)
        self.assertEqual(
            AlertRepository(self.backend).list_alerts(active_only=True, instance_id="instance-1"),
            [],
        )

    def test_info_event_does_not_open_alert(self):
        events = UniversalEventRepository(self.backend)
        engine = DatabaseAlertEngine(self.backend)
        engine.cycle()
        events.publish({
            "event_id": "info-event-1",
            "event_type": "INSTANCE_STARTED",
            "source": "controller.runtime",
            "severity": "info",
            "agent_id": "agent-1",
            "instance_id": "instance-1",
            "data": {},
        })
        engine.cycle()
        alerts = AlertRepository(self.backend).list_alerts(active_only=True)
        self.assertEqual(alerts, [])

    def test_steam_auth_detection_is_explicit_and_not_generic_auth_text(self):
        detector = AgentInstanceProvisioningRepository._steam_auth_required
        self.assertTrue(detector("Steam Guard code required", {}))
        self.assertTrue(detector("", {"steam_auth_required": True}))
        self.assertFalse(detector("generic authentication failure", {}))


if __name__ == "__main__":
    unittest.main()
