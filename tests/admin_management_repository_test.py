#!/usr/bin/env python3

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "database"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from admin_management_repository import AdminManagementRepository
from backend import DatabaseConfig
from backend_factory import create_backend
from registry import installation_profile_identity
from registry_repository import RegistryRepository


class AdminManagementRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(DatabaseConfig(
            driver="sqlite",
            database=str(Path(self.temp.name) / "capivara.db"),
        ))
        self.backend.initialize()
        identity = installation_profile_identity(
            RegistryRepository(self.backend),
            profile="controller",
            hostname="admin-cli-controller",
        )
        self.controller_id = str(identity["controller_id"])
        self.repository = AdminManagementRepository(self.backend)
        self.repository.initialize()

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_create_customer_creates_scoped_login_in_same_operation(self):
        result = self.repository.create_customer(
            customer_id="CLIENTE-001",
            name="Cliente Teste",
            username="cliente.teste",
            password_hash="test-hash",
        )
        self.assertEqual(result["controller_id"], self.controller_id)
        with self.repository.session() as session:
            customer = session.execute(
                "SELECT status FROM customers WHERE id=?", ("CLIENTE-001",)
            ).fetchone()
            user = session.execute(
                "SELECT role,scope_id FROM dashboard_users WHERE username=?",
                ("cliente.teste",),
            ).fetchone()
        self.assertEqual(customer["status"], "active")
        self.assertEqual(user["role"], "customer")
        self.assertEqual(user["scope_id"], "CLIENTE-001")

    def test_create_contract_binds_customer_game_and_limit(self):
        self.repository.create_customer(
            customer_id="CLIENTE-001",
            name="Cliente Teste",
            username="cliente.teste",
            password_hash="test-hash",
        )
        result = self.repository.create_contract(
            customer_id="CLIENTE-001",
            game_id="dayz",
            instance_limit=2,
            contract_id="CONTRACT-DAYZ-001",
        )
        self.assertEqual(result["id"], "CONTRACT-DAYZ-001")
        self.assertEqual(result["game_id"], "dayz")
        self.assertEqual(result["instance_limit"], 2)

    def test_contract_rejects_missing_customer(self):
        with self.assertRaises(ValueError):
            self.repository.create_contract(
                customer_id="MISSING-001",
                game_id="dayz",
                instance_limit=1,
            )


if __name__ == "__main__":
    unittest.main()
