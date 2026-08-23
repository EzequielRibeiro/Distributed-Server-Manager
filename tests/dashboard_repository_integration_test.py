#!/usr/bin/env python3
"""Real database integration tests for DashboardRepository."""

import json
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "database"))

from dashboard_repository import DashboardRepository
from runtime_backend import backend_from_environment

ENABLED = os.environ.get("DSM_DASHBOARD_REPOSITORY_INTEGRATION", "").strip() == "1"


@unittest.skipUnless(ENABLED, "set DSM_DASHBOARD_REPOSITORY_INTEGRATION=1")
class DashboardRepositoryIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repository = DashboardRepository(backend_from_environment())
        cls.repository.initialize()

    @classmethod
    def tearDownClass(cls):
        cls.repository.close()

    def setUp(self):
        suffix = uuid.uuid4().hex
        self.ids = {name: f"dashboard-{name}-{suffix}" for name in (
            "controller_node", "agent_node", "controller", "agent",
            "customer", "contract", "user",
        )}
        d = self.repository.dialect
        with self.repository.session(transaction=True) as session:
            for key, role in (("controller_node", "controller"), ("agent_node", "agent")):
                session.execute(
                    "INSERT INTO nodes(id,name,role,status) VALUES "
                    f"({d.parameters(4)})",
                    (self.ids[key], key, role, "active"),
                )
            session.execute(
                "INSERT INTO controllers(id,node_id,name,status) VALUES "
                f"({d.parameters(4)})",
                (self.ids["controller"], self.ids["controller_node"], "Controller", "active"),
            )
            session.execute(
                "INSERT INTO agents(id,controller_id,node_id,name,status) VALUES "
                f"({d.parameters(5)})",
                (self.ids["agent"], self.ids["controller"], self.ids["agent_node"], "Agent", "active"),
            )
            session.execute(
                "INSERT INTO customers(id,controller_id,name,status) VALUES "
                f"({d.parameters(4)})",
                (self.ids["customer"], self.ids["controller"], "Customer", "active"),
            )
            session.execute(
                "INSERT INTO service_contracts(id,customer_id,game_id,status,instance_limit) VALUES "
                f"({d.parameters(5)})",
                (self.ids["contract"], self.ids["customer"], "minecraft", "active", 1),
            )
        self.temp = tempfile.TemporaryDirectory()
        self.instance_id = None

    def tearDown(self):
        ph = self.repository.dialect.placeholder
        with self.repository.session(transaction=True) as session:
            session.execute(
                f"DELETE FROM audit_log WHERE username={ph}", (self.ids["user"],)
            )
            session.execute(
                f"DELETE FROM dashboard_users WHERE username={ph}", (self.ids["user"],)
            )
            if self.instance_id:
                session.execute(f"DELETE FROM instances WHERE id={ph}", (self.instance_id,))
            session.execute(f"DELETE FROM service_contracts WHERE id={ph}", (self.ids["contract"],))
            session.execute(f"DELETE FROM customers WHERE id={ph}", (self.ids["customer"],))
            session.execute(f"DELETE FROM agents WHERE id={ph}", (self.ids["agent"],))
            session.execute(f"DELETE FROM controllers WHERE id={ph}", (self.ids["controller"],))
            session.execute(f"DELETE FROM nodes WHERE id={ph}", (self.ids["agent_node"],))
            session.execute(f"DELETE FROM nodes WHERE id={ph}", (self.ids["controller_node"],))
        self.temp.cleanup()

    def test_customer_instance_and_runtime_queries(self):
        plan = self.repository.create_customer_instance(
            customer_id=self.ids["customer"], username=self.ids["user"],
            game="minecraft", runtime_id="minecraft.vanilla", edition="vanilla",
            variant=None, version="latest", build="default",
            instances_root=Path(self.temp.name),
        )
        self.instance_id = plan["instance_id"]
        self.assertEqual(plan["agent_id"], self.ids["agent"])
        self.assertEqual(self.repository.instance_context(self.instance_id)["customer_id"],
                         self.ids["customer"])
        self.assertEqual(self.repository.update_instance_status(self.instance_id, "online"), 1)
        self.assertIn(
            (self.ids["agent_node"], "minecraft", self.instance_id),
            self.repository.registered_instances(),
        )

    def test_customer_contracts_are_json_serializable(self):
        contracts = self.repository.customer_contracts(self.ids["customer"])
        self.assertEqual(contracts[0]["id"], self.ids["contract"])
        json.dumps({"contracts": contracts})

    def test_users_scopes_and_audit(self):
        self.repository.save_user(
            self.ids["user"], "hash", "customer", self.ids["customer"], True
        )
        self.assertEqual(self.repository.permission_profile(self.ids["user"], "missing"), None)
        self.assertIn(self.ids["user"], {row["username"] for row in self.repository.load_users()})
        self.repository.write_audit(self.ids["user"], None, "test", "success", None)
        options = self.repository.scope_options()
        self.assertIn(self.ids["customer"], {row["id"] for row in options["customers"]})


if __name__ == "__main__":
    unittest.main()
