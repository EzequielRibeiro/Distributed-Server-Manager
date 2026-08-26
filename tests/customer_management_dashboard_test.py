#!/usr/bin/env python3
from __future__ import annotations

import base64
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
from customer_http_auth import authenticate_customer
from customer_management_repository import CustomerManagementRepository
from registry import installation_profile_identity
from registry_repository import RegistryRepository


class CustomerManagementRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(
            DatabaseConfig(
                driver="sqlite",
                database=str(Path(self.temp.name) / "capivara.db"),
            )
        )
        identity = installation_profile_identity(
            RegistryRepository(self.backend),
            profile="controller",
            hostname="customer-management-controller",
        )
        self.controller_id = str(identity["controller_id"])
        self.repository = CustomerManagementRepository(self.backend)

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def _create(self, **overrides):
        payload = {
            "name": "Cliente Teste",
            "legal_name": "Cliente Teste LTDA",
            "document_type": "cnpj",
            "document_number": "12.345.678/0001-90",
            "username": "cliente.teste",
            "email": "cliente@example.com",
            "phone": "+55 19 99999-9999",
            "controller_id": self.controller_id,
            "billing_provider": "stripe",
            "billing_customer_id": "cus_test_001",
            "billing_status": "active",
        }
        payload.update(overrides)
        return self.repository.create_account(**payload)

    @staticmethod
    def _basic(login: str, password: str) -> dict[str, str]:
        token = base64.b64encode(f"{login}:{password}".encode()).decode()
        return {"Authorization": f"Basic {token}"}

    def test_create_account_is_atomic_and_login_accepts_username_or_email(self):
        created = self._create()
        self.assertEqual(created["customer_code"], "CLI-000001")
        self.assertEqual(created["document_number"], "12345678000190")
        self.assertTrue(created["must_change_password"])

        by_username = authenticate_customer(
            self._basic(created["username"], created["temporary_password"]),
            self.backend,
        )
        by_email = authenticate_customer(
            self._basic(created["email"], created["temporary_password"]),
            self.backend,
        )
        self.assertIsNotNone(by_username)
        self.assertIsNotNone(by_email)
        self.assertEqual(by_username["customer_id"], created["id"])
        self.assertEqual(by_email["customer_id"], created["id"])

        with self.backend.connect() as connection:
            state = connection.execute(
                "SELECT must_change_password FROM customer_password_state WHERE username=?",
                (created["username"],),
            ).fetchone()
            customer = connection.execute(
                "SELECT account_email,email_verified_at,registration_status "
                "FROM customers WHERE id=?",
                (created["id"],),
            ).fetchone()
        self.assertEqual(int(state["must_change_password"]), 1)
        self.assertEqual(customer["account_email"], "cliente@example.com")
        self.assertIsNotNone(customer["email_verified_at"])
        self.assertEqual(customer["registration_status"], "active")

    def test_username_and_email_are_unique_without_partial_customer_rows(self):
        created = self._create()
        with self.assertRaisesRegex(ValueError, "username already exists"):
            self._create(
                username="CLIENTE.TESTE",
                email="outro@example.com",
                billing_customer_id="cus_test_002",
            )
        with self.assertRaisesRegex(ValueError, "e-mail already exists"):
            self._create(
                username="outro.usuario",
                email="CLIENTE@example.com",
                billing_customer_id="cus_test_003",
            )
        with self.backend.connect() as connection:
            customers = connection.execute("SELECT COUNT(*) AS total FROM customers").fetchone()
            users = connection.execute("SELECT COUNT(*) AS total FROM dashboard_users WHERE role='customer'").fetchone()
            identities = connection.execute("SELECT COUNT(*) AS total FROM customer_user_identities").fetchone()
        self.assertEqual(int(customers["total"]), 1)
        self.assertEqual(int(users["total"]), 1)
        self.assertEqual(int(identities["total"]), 1)
        self.assertEqual(created["customer_code"], "CLI-000001")

    def test_search_supports_name_email_document_and_customer_code(self):
        created = self._create()
        cases = (
            ("name", "Cliente Teste"),
            ("email", "cliente@example.com"),
            ("document", "12.345.678/0001-90"),
            ("customer_code", created["customer_code"]),
        )
        for field, query in cases:
            with self.subTest(field=field):
                result = self.repository.search(query, field)
                self.assertEqual(len(result), 1)
                self.assertEqual(result[0]["customer_code"], created["customer_code"])

    def test_detail_exposes_billing_contract_status_and_profile(self):
        created = self._create()
        contract = self.repository.create_contract(
            customer_code=created["customer_code"],
            game_id="dayz",
            instance_limit=2,
            ends_at=None,
            resource_profile_id="medium",
            resource_profile_source="selected",
        )
        detail = self.repository.detail(created["customer_code"])
        self.assertEqual(detail["customer"]["billing_provider"], "stripe")
        self.assertEqual(detail["customer"]["billing_status"], "active")
        self.assertEqual(detail["contracts"][0]["id"], contract["id"])
        self.assertEqual(detail["contracts"][0]["status"], "active")
        self.assertEqual(detail["contracts"][0]["resource_profile_id"], "medium")


class CustomerManagementPostgreSQLContractTest(unittest.TestCase):
    def test_detail_uses_boolean_default_for_postgresql_password_state(self):
        source = (
            ROOT / "database" / "customer_management_repository.py"
        ).read_text(encoding="utf-8")

        self.assertIn(
            'password_default = "FALSE" if self.backend.name == "postgresql" else "0"',
            source,
        )
        self.assertIn(
            'f"COALESCE(ps.must_change_password,{password_default}) AS must_change_password "',
            source,
        )
        self.assertNotIn(
            "COALESCE(ps.must_change_password,0) AS must_change_password",
            source,
        )



class CustomerManagementAssetContractTest(unittest.TestCase):
    def test_pages_keep_creation_lookup_detail_and_contract_separate(self):
        web = ROOT / "dashboard" / "web"
        lookup = (web / "customers.html").read_text(encoding="utf-8")
        create = (web / "customer-create.html").read_text(encoding="utf-8")
        detail = (web / "customer-admin.html").read_text(encoding="utf-8")
        contract = (web / "customer-contract-create.html").read_text(encoding="utf-8")

        self.assertIn("customer-search-field", lookup)
        self.assertNotIn("customer-create-form", lookup)
        self.assertNotIn("contract-create-form", lookup)

        self.assertIn("customer-create-form", create)
        self.assertIn("customer-username", create)
        self.assertIn("customer-email", create)
        self.assertIn("customer-document-number", create)
        self.assertNotIn("customer-search-field", create)
        self.assertNotIn("contract-game", create)

        self.assertIn("detail-billing", detail)
        self.assertIn("detail-contracts", detail)
        self.assertNotIn("contract-create-form", detail)
        self.assertNotIn("customer-create-form", detail)

        self.assertIn("contract-create-form", contract)
        self.assertIn("contract-profile", contract)
        self.assertNotIn("customer-create-form", contract)
        self.assertNotIn("customer-search-field", contract)


if __name__ == "__main__":
    unittest.main()
