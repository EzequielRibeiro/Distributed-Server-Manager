#!/usr/bin/env python3

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "database"))

from backend import DatabaseConfig
from backend_factory import create_backend
from customer_repository import CustomerRepository, mask_document, normalize_document
import customers as legacy_customers


class CustomerRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "capivara.db"
        backend = create_backend(DatabaseConfig(
            driver="sqlite", database=str(self.database)
        ))
        self.repository = CustomerRepository(backend)
        self.repository.initialize()
        with self.repository.backend.transaction() as connection:
            connection.execute("INSERT INTO nodes(id,name,role,status) VALUES (?,?,?,?)",
                               ("node1", "Node", "controller", "active"))
            connection.execute("INSERT INTO controllers(id,node_id,name,status) VALUES (?,?,?,?)",
                               ("controller1", "node1", "Controller", "active"))
            connection.execute("""INSERT INTO customers(
                id,controller_id,name,legal_name,email,status,document_type,document_number)
                VALUES (?,?,?,?,?,?,?,?)""",
                ("customer1", "controller1", "Árvore Games", "Arvore Legal",
                 "billing@example.test", "active", "cpf", "12345678901"))

    def tearDown(self):
        self.repository.close()
        self.temp.cleanup()

    def test_document_helpers(self):
        self.assertEqual(normalize_document("123.456-78"), "12345678")
        self.assertEqual(mask_document("cpf", "12345678901"), "***.***.***-01")

    def test_search_masks_document_and_counts(self):
        page = self.repository.search_customers(query="billing@example", limit=10)
        self.assertEqual(page["total"], 1)
        self.assertEqual(page["items"][0]["document"], "***.***.***-01")
        self.assertNotIn("document_number", page["items"][0])
        self.assertEqual(page["items"][0]["instance_count"], 0)

    def test_search_validates_status_and_pagination(self):
        with self.assertRaisesRegex(ValueError, "invalid customer status"):
            self.repository.search_customers(status="unknown")
        with self.assertRaisesRegex(ValueError, "invalid pagination"):
            self.repository.search_customers(limit="bad")

    def test_get_customer_contract(self):
        customer = self.repository.get_customer("customer1")
        self.assertEqual(customer["controller_name"], "Controller")
        self.assertEqual(customer["users"], [])
        self.assertEqual(customer["contracts"], [])
        self.assertEqual(customer["instances"], [])
        self.assertEqual(customer["permissions"], [])
        self.assertEqual(customer["audit"], [])
        self.assertIsNone(self.repository.get_customer("missing"))

    def test_search_matches_legacy_sqlite_contract(self):
        expected = legacy_customers.search_customers(
            self.database,
            query="billing@example",
            status="active",
            limit=10,
            offset=0,
        )
        actual = self.repository.search_customers(
            query="billing@example",
            status="active",
            limit=10,
            offset=0,
        )
        self.assertEqual(actual, expected)

    def test_detail_matches_legacy_sqlite_contract(self):
        expected = legacy_customers.get_customer(
            self.database,
            "customer1",
        )
        actual = self.repository.get_customer("customer1")
        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
