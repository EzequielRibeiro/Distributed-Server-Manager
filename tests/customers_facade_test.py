#!/usr/bin/env python3

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "database"))

import customers
from backend import DatabaseConfig
from backend_factory import create_backend


class CustomersFacadeTest(unittest.TestCase):
    def test_path_delegates_search(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(
                customers.CustomerRepository,
                "search_customers",
                return_value={"items": []},
            ) as search:
                result = customers.search_customers(
                    Path(temp) / "capivara.db",
                    query="customer",
                )
        self.assertEqual(result, {"items": []})
        search.assert_called_once_with(
            query="customer", status="", limit=50, offset=0
        )

    def test_backend_delegates_detail(self):
        with tempfile.TemporaryDirectory() as temp:
            backend = create_backend(DatabaseConfig(
                driver="sqlite",
                database=str(Path(temp) / "capivara.db"),
            ))
            with patch.object(
                customers.CustomerRepository,
                "get_customer",
                return_value={"id": "customer1"},
            ) as get_customer:
                result = customers.get_customer(backend, "customer1")
        self.assertEqual(result, {"id": "customer1"})
        get_customer.assert_called_once_with("customer1")

    def test_public_helpers_are_preserved(self):
        self.assertEqual(
            customers.normalize_document("123.456-78"),
            "12345678",
        )
        self.assertEqual(
            customers.mask_document("cpf", "12345678901"),
            "***.***.***-01",
        )


if __name__ == "__main__":
    unittest.main()
