#!/usr/bin/env python3

import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "database"))

from backend import DatabaseConfig
from backend_factory import create_backend
from dashboard_repository import DashboardRepository, _json_ready_row
from registry_repository import RegistryRepository


class DashboardRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        backend = create_backend(DatabaseConfig(
            driver="sqlite", database=str(Path(self.temp.name) / "capivara.db")
        ))
        self.repository = DashboardRepository(backend)
        self.repository.initialize()
        RegistryRepository(backend).create_aurora(
            password_hash="hash",
            manifest_path="manifest",
            metadata_json="{}",
        )

    def tearDown(self):
        self.repository.close()
        self.temp.cleanup()

    def test_postgresql_temporal_values_are_json_ready(self):
        row = _json_ready_row({
            "starts_at": datetime(2026, 8, 23, 5, 0, tzinfo=timezone.utc),
            "ends_at": date(2026, 9, 23),
            "instances_used": 0,
        })
        self.assertEqual(row["starts_at"], "2026-08-23T05:00:00+00:00")
        self.assertEqual(row["ends_at"], "2026-09-23")
        self.assertEqual(row["instances_used"], 0)
        json.dumps({"contracts": [row]})

    def test_instance_status_context_and_registry(self):
        self.assertEqual(self.repository.update_instance_status("cliente-demo", "online"), 1)
        self.assertEqual(self.repository.instance_context("cliente-demo")["node_id"], "DemoNode")
        self.assertIn(("DemoNode", "minecraft", "cliente-demo"),
                      self.repository.registered_instances())

    def test_users_scopes_audit_and_delete(self):
        self.assertEqual(self.repository.load_users()[0]["username"], "aurora")
        options = self.repository.scope_options()
        self.assertEqual(options["controllers"][0]["id"], "controller-demo")
        self.assertEqual(options["customers"][0]["id"], "CLI-DEMO-001")
        self.repository.write_audit("aurora", "cliente-demo", "test", "success", None)
        self.assertEqual(self.repository.delete_instance("cliente-demo"), 1)

    def test_delete_instance_preserves_instance_alert_as_node_history(self):
        instance_id = "cliente-demo"
        alert_id = "test-delete-alert:cliente-demo"

        with self.repository.session(transaction=True) as session:
            session.execute(
                """
                INSERT INTO alerts(
                    id,
                    scope,
                    controller_id,
                    agent_id,
                    node_id,
                    instance_id,
                    rule_id,
                    level,
                    state,
                    message
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alert_id,
                    "instance",
                    "controller-demo",
                    "agent-demo",
                    "DemoNode",
                    instance_id,
                    "test.instance.delete",
                    "CRITICAL",
                    "RESOLVED",
                    "Alerta histórico de teste",
                ),
            )

        self.assertEqual(
            self.repository.delete_instance(instance_id),
            1,
        )

        self.assertIsNone(
            self.repository.instance_context(instance_id)
        )

        with self.repository.session() as session:
            alert = session.execute(
                """
                SELECT
                    scope,
                    controller_id,
                    agent_id,
                    node_id,
                    instance_id,
                    state,
                    message
                FROM alerts
                WHERE id=?
                """,
                (alert_id,),
            ).fetchone()

        self.assertIsNotNone(alert)
        self.assertEqual(alert["scope"], "node")
        self.assertEqual(alert["controller_id"], "controller-demo")
        self.assertEqual(alert["agent_id"], "agent-demo")
        self.assertEqual(alert["node_id"], "DemoNode")
        self.assertIsNone(alert["instance_id"])
        self.assertEqual(alert["state"], "RESOLVED")
        self.assertEqual(
            alert["message"],
            "Alerta histórico de teste",
        )

    def test_customer_instance_reservation_and_retry(self):
        plan = self.repository.create_customer_instance(
            customer_id="CLI-DEMO-001",
            username="aurora",
            game="dayz",
            runtime_id="dayz.stable",
            edition="stable",
            variant=None,
            version="latest",
            build="default",
            instances_root=Path(self.temp.name) / "instances",
            network_profile={
                "allocation": "block",
                "block_size": 10,
                "ports": [
                    {
                        "name": "game",
                        "protocol": "udp",
                        "offset": 0,
                    },
                    {
                        "name": "game_aux",
                        "protocol": "udp",
                        "offset": 2,
                    },
                ],
            },
            occupied_ports_provider=(
                lambda agent_id, node_id, protocol, start_port, end_port:
                    {24000, 24002}
                    if protocol == "udp"
                    else set()
            ),
        )
        self.assertEqual(plan["instance_id"], "cli-demo-001-dayz-001")
        self.assertEqual(plan["game_port"], 24010)
        self.assertEqual(plan["ports"]["game_aux"], 24012)
        self.repository.update_instance_status(plan["instance_id"], "failed")
        reserved = self.repository.reserve_retry(
            plan["instance_id"], "DemoNode", "dayz"
        )
        self.assertEqual(reserved["status"], "failed")
        self.assertEqual(
            self.repository.instance_context(plan["instance_id"])["node_id"],
            "DemoNode",
        )

    def test_runtime_reconciliation_preserves_provision_states(self):
        instance_id = "cliente-demo"
        for protected in (
            "queued", "provisioning", "installing",
            "pending_steam_auth", "failed",
        ):
            self.repository.update_instance_status(instance_id, protected)
            self.assertEqual(
                self.repository.reconcile_instance_status(instance_id, "offline"),
                0,
            )
            with self.repository.session() as session:
                row = session.execute(
                    "SELECT status FROM instances WHERE id=?", (instance_id,)
                ).fetchone()
            self.assertEqual(row["status"], protected)

        self.repository.update_instance_status(instance_id, "online")
        self.assertEqual(
            self.repository.reconcile_instance_status(instance_id, "offline"), 1
        )


if __name__ == "__main__":
    unittest.main()
