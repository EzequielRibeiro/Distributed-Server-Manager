#!/usr/bin/env python3
"""Real database integration tests for RegistryRepository."""

import os
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "database"))

from registry_repository import RegistryRepository
from runtime_backend import backend_from_environment

ENABLED = os.environ.get("DSM_REGISTRY_REPOSITORY_INTEGRATION", "").strip() == "1"


@unittest.skipUnless(ENABLED, "set DSM_REGISTRY_REPOSITORY_INTEGRATION=1")
class RegistryRepositoryIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repository = RegistryRepository(backend_from_environment())
        cls.repository.initialize()

    @classmethod
    def tearDownClass(cls):
        cls.repository.close()

    def setUp(self):
        suffix = uuid.uuid4().hex
        self.controller_node = f"registry-controller-node-{suffix}"
        self.node = f"registry-agent-node-{suffix}"
        self.controller = f"registry-controller-{suffix}"
        self.agent = f"registry-agent-{suffix}"
        self.customer = f"registry-customer-{suffix}"
        self.instance = f"registry-instance-{suffix}"
        d = self.repository.dialect
        with self.repository.transaction() as session:
            for node_id, role in (
                (self.controller_node, "controller"),
                (self.node, "agent"),
            ):
                session.execute(
                    "INSERT INTO nodes(id,name,role,status) VALUES "
                    f"({d.parameters(4)})",
                    (node_id, "Registry Node", role, "active"),
                )
            session.execute(
                "INSERT INTO controllers(id,node_id,name,status) VALUES "
                f"({d.parameters(4)})",
                (self.controller, self.controller_node, "Controller", "active"),
            )
            session.execute(
                "INSERT INTO agents(id,controller_id,node_id,name,status) VALUES "
                f"({d.parameters(5)})",
                (self.agent, self.controller, self.node, "Agent", "active"),
            )
            session.execute(
                "INSERT INTO customers(id,controller_id,name,status) VALUES "
                f"({d.parameters(4)})",
                (self.customer, self.controller, "Customer", "active"),
            )
            session.execute(
                "INSERT INTO instances(id,node_id,game_id,name,status,controller_id,agent_id,customer_id) VALUES "
                f"({d.parameters(8)})",
                (self.instance, self.node, "minecraft", "Registry Instance", "offline",
                 self.controller, self.agent, self.customer),
            )

    def tearDown(self):
        ph = self.repository.dialect.placeholder
        with self.repository.transaction() as session:
            session.execute(f"DELETE FROM instances WHERE id={ph}", (self.instance,))
            session.execute(f"DELETE FROM customers WHERE id={ph}", (self.customer,))
            session.execute(f"DELETE FROM agents WHERE id={ph}", (self.agent,))
            session.execute(f"DELETE FROM controllers WHERE id={ph}", (self.controller,))
            session.execute(f"DELETE FROM nodes WHERE id={ph}", (self.node,))
            session.execute(f"DELETE FROM nodes WHERE id={ph}", (self.controller_node,))

    def test_get_and_delete_instance(self):
        row = self.repository.get_instance(self.instance)
        self.assertEqual(row["node_id"], self.node)
        self.repository.delete_instance(self.instance)
        self.assertIsNone(self.repository.get_instance(self.instance))

    def test_missing_instance(self):
        self.assertIsNone(self.repository.get_instance("missing-registry-instance"))


if __name__ == "__main__":
    unittest.main()
