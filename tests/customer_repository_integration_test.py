#!/usr/bin/env python3
"""Real database integration tests for CustomerRepository."""

import os
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "database"))

from customer_repository import CustomerRepository
from runtime_backend import backend_from_environment

ENABLED = os.environ.get("DSM_CUSTOMER_REPOSITORY_INTEGRATION", "").strip() == "1"


@unittest.skipUnless(ENABLED, "set DSM_CUSTOMER_REPOSITORY_INTEGRATION=1")
class CustomerRepositoryIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repository = CustomerRepository(backend_from_environment())
        cls.repository.initialize()

    @classmethod
    def tearDownClass(cls):
        cls.repository.close()

    def setUp(self):
        suffix = uuid.uuid4().hex
        self.node = f"customer-test-node-{suffix}"
        self.controller = f"customer-test-controller-{suffix}"
        self.customer = f"customer-test-{suffix}"
        p = self.repository.dialect
        with self.repository.backend.transaction() as connection:
            from alert_repository import AlertSession
            session = AlertSession(self.repository.backend, connection)
            session.execute("INSERT INTO nodes(id,name,role,status) VALUES "
                            f"({p.parameters(4)})",
                            (self.node, "Integration Node", "controller", "active"))
            session.execute("INSERT INTO controllers(id,node_id,name,status) VALUES "
                            f"({p.parameters(4)})",
                            (self.controller, self.node, "Integration Controller", "active"))
            session.execute("""INSERT INTO customers(
                id,controller_id,name,legal_name,email,status,document_type,document_number)
                VALUES """ + f"({p.parameters(8)})",
                (self.customer, self.controller, "Integration Customer", "Integration Legal",
                 f"{suffix}@example.test", "active", "cpf", "12345678901"))
            session.close()

    def tearDown(self):
        p = self.repository.dialect.placeholder
        with self.repository.backend.transaction() as connection:
            from alert_repository import AlertSession
            session = AlertSession(self.repository.backend, connection)
            session.execute(f"DELETE FROM customers WHERE id={p}", (self.customer,))
            session.execute(f"DELETE FROM controllers WHERE id={p}", (self.controller,))
            session.execute(f"DELETE FROM nodes WHERE id={p}", (self.node,))
            session.close()

    def test_search_customer(self):
        page = self.repository.search_customers(
            query=self.customer,
            status="active",
            limit=1,
        )
        self.assertEqual(page["total"], 1)
        self.assertEqual(page["items"][0]["id"], self.customer)
        self.assertEqual(page["items"][0]["document"], "***.***.***-01")

    def test_customer_detail(self):
        customer = self.repository.get_customer(self.customer)
        self.assertEqual(customer["controller_id"], self.controller)
        self.assertEqual(customer["controller_name"], "Integration Controller")
        self.assertEqual(customer["users"], [])
        self.assertEqual(customer["audit"], [])


if __name__ == "__main__":
    unittest.main()
