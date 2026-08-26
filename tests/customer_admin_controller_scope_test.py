#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "database", ROOT / "dashboard"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from backend import DatabaseConfig
from backend_factory import create_backend
from customer_management_repository import CustomerManagementRepository
from customer_profile_admin_http import update_customer_profile_for_user
from registry import installation_profile_identity
from registry_repository import RegistryRepository


class CustomerAdminControllerScopeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(DatabaseConfig(driver="sqlite", database=str(Path(self.temp.name) / "capivara.db")))
        identity = installation_profile_identity(
            RegistryRepository(self.backend), profile="controller", hostname="customer-scope-controller"
        )
        self.controller_id = str(identity["controller_id"])
        self.management = CustomerManagementRepository(self.backend)
        created = self.management.create_account(
            name="Cliente Scope",
            legal_name="Cliente Scope Ltda",
            document_type="other",
            document_number="SCOPE-001",
            username="cliente.scope",
            email="scope@example.test",
            phone="11999990001",
            controller_id=self.controller_id,
            billing_provider="testbilling",
            billing_customer_id="billing-scope-001",
            billing_status="active",
        )
        self.code = str(created["customer_code"])

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_controller_cannot_reassign_customer_to_another_controller(self):
        status, response = update_customer_profile_for_user(
            {"customer_code": self.code, "changes": {"controller_id": "controller-other"}},
            user={"username": "controller-user", "role": "controller", "scope_id": self.controller_id},
            backend=self.backend,
        )
        self.assertEqual(status, 403)
        self.assertEqual(response["error"], "forbidden")
        current = self.management.detail(self.code)["customer"]
        self.assertEqual(str(current["controller_id"]), self.controller_id)

    def test_admin_may_request_controller_reassignment(self):
        status, response = update_customer_profile_for_user(
            {"customer_code": self.code, "changes": {"controller_id": self.controller_id}},
            user={"username": "admin", "role": "admin"},
            backend=self.backend,
        )
        self.assertEqual(status, 200)
        self.assertFalse(response["updated"])


if __name__ == "__main__":
    unittest.main()
