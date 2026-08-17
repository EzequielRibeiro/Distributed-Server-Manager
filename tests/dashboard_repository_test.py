#!/usr/bin/env python3

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "database"))

from backend import DatabaseConfig
from backend_factory import create_backend
from dashboard_repository import DashboardRepository
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
            unavailable_ports_provider=lambda: {24000},
        )
        self.assertEqual(plan["instance_id"], "cli-demo-001-dayz-001")
        self.assertEqual(plan["game_port"], 24001)
        self.repository.update_instance_status(plan["instance_id"], "failed")
        reserved = self.repository.reserve_retry(
            plan["instance_id"], "DemoNode", "dayz"
        )
        self.assertEqual(reserved["status"], "failed")
        self.assertEqual(
            self.repository.instance_context(plan["instance_id"])["node_id"],
            "DemoNode",
        )


if __name__ == "__main__":
    unittest.main()
