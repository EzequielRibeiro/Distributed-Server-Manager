#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "database", ROOT / "dashboard"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from alert_repository import AlertSession
from backend import DatabaseConfig
from backend_factory import create_backend
from customer_management_repository import CustomerManagementRepository
from customer_profile_admin_http import update_customer_profile_for_user
from customer_profile_admin_repository import CustomerProfileAdminRepository
from registry import installation_profile_identity
from registry_repository import RegistryRepository
from universal_event_repository import UniversalEventRepository


class CustomerAdminEditingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(DatabaseConfig(driver="sqlite", database=str(Path(self.temp.name) / "capivara.db")))
        identity = installation_profile_identity(
            RegistryRepository(self.backend), profile="controller", hostname="customer-edit-controller"
        )
        self.controller_id = str(identity["controller_id"])
        self.management = CustomerManagementRepository(self.backend)
        created = self.management.create_account(
            name="Cliente Original",
            legal_name="Cliente Original Ltda",
            document_type="other",
            document_number="DOC-001",
            username="cliente.original",
            email="original@example.test",
            phone="11999990000",
            controller_id=self.controller_id,
            billing_provider="testbilling",
            billing_customer_id="billing-001",
            billing_status="active",
        )
        self.code = str(created["customer_code"])
        self.customer_id = int(created["id"])

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def _audit(self):
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = session.execute(
                    "SELECT username,action,result,details FROM audit_log ORDER BY id DESC LIMIT 1"
                ).fetchone()
                return dict(row) if row is not None else None
            finally:
                session.close()

    def test_admin_updates_profile_and_preserves_identity_and_user(self):
        before = self.management.detail(self.code)
        status, response = update_customer_profile_for_user(
            {
                "customer_code": self.code,
                "correlation_id": "corr-customer-edit-1",
                "changes": {
                    "name": "Cliente Atualizado",
                    "legal_name": "Cliente Atualizado Ltda",
                    "phone": "11988887777",
                    "document_type": "cnpj",
                    "document_number": "12345678000199",
                    "billing_status": "past_due",
                },
            },
            user={"username": "admin", "role": "admin"},
            backend=self.backend,
        )
        self.assertEqual(status, 200)
        self.assertTrue(response["updated"])
        self.assertEqual(response["customer"]["name"], "Cliente Atualizado")
        self.assertEqual(response["customer"]["billing_status"], "past_due")
        self.assertEqual(response["customer"]["id"], before["customer"]["id"])
        self.assertEqual(response["customer"]["customer_code"], before["customer"]["customer_code"])
        self.assertEqual(response["customer"]["account_email"], before["customer"]["account_email"])
        after = self.management.detail(self.code)
        self.assertEqual([u["username"] for u in after["users"]], [u["username"] for u in before["users"]])
        self.assertEqual(after["contracts"], before["contracts"])
        self.assertEqual(after["instances"], before["instances"])

        audit = self._audit()
        self.assertEqual(audit["action"], "CUSTOMER_PROFILE_UPDATED")
        self.assertEqual(audit["result"], "success")
        details = json.loads(audit["details"])
        self.assertEqual(details["correlation_id"], "corr-customer-edit-1")
        self.assertEqual(details["before"]["name"], "Cliente Original")
        self.assertEqual(details["after"]["name"], "Cliente Atualizado")
        self.assertNotIn("account_email", details["after"])

        events = UniversalEventRepository(self.backend).list_events(
            event_type="CUSTOMER_PROFILE_UPDATED", correlation_id="corr-customer-edit-1", limit=10
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["data"]["customer_code"], self.code)

    def test_controller_scope_is_enforced(self):
        status, _ = update_customer_profile_for_user(
            {"customer_code": self.code, "changes": {"phone": "11111111111"}},
            user={"username": "controller-ok", "role": "controller", "scope_id": self.controller_id},
            backend=self.backend,
        )
        self.assertEqual(status, 200)
        status, response = update_customer_profile_for_user(
            {"customer_code": self.code, "changes": {"phone": "22222222222"}},
            user={"username": "controller-other", "role": "controller", "scope_id": "controller-other"},
            backend=self.backend,
        )
        self.assertEqual(status, 403)
        self.assertEqual(response["error"], "forbidden")

    def test_customer_role_cannot_edit_profile(self):
        status, response = update_customer_profile_for_user(
            {"customer_code": self.code, "changes": {"name": "Não permitido"}},
            user={"username": "cliente.original", "role": "customer"},
            backend=self.backend,
        )
        self.assertEqual(status, 403)
        self.assertEqual(response["error"], "forbidden")

    def test_identity_and_email_fields_are_immutable(self):
        repo = CustomerProfileAdminRepository(self.backend)
        for field, value in (
            ("id", 999),
            ("customer_code", "CLI999999"),
            ("account_email", "attacker@example.test"),
            ("email", "attacker@example.test"),
            ("username", "attacker"),
        ):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    repo.update(self.code, {field: value})
        current = self.management.detail(self.code)["customer"]
        self.assertEqual(current["id"], self.customer_id)
        self.assertEqual(current["customer_code"], self.code)
        self.assertEqual(current["account_email"], "original@example.test")

    def test_rejected_email_change_audit_does_not_store_proposed_secret_value(self):
        proposed = "private-new-address@example.test"
        status, _ = update_customer_profile_for_user(
            {"customer_code": self.code, "changes": {"account_email": proposed}},
            user={"username": "admin", "role": "admin"},
            backend=self.backend,
        )
        self.assertEqual(status, 400)
        audit = self._audit()
        self.assertEqual(audit["result"], "rejected")
        self.assertNotIn(proposed, audit["details"])

    def test_invalid_document_and_billing_status_are_rejected(self):
        repo = CustomerProfileAdminRepository(self.backend)
        with self.assertRaises(ValueError):
            repo.update(self.code, {"document_type": "cpf", "document_number": "123"})
        with self.assertRaises(ValueError):
            repo.update(self.code, {"billing_status": "invented-status"})

    def test_noop_does_not_emit_event(self):
        current = self.management.detail(self.code)["customer"]
        status, response = update_customer_profile_for_user(
            {"customer_code": self.code, "changes": {"name": current["name"]}},
            user={"username": "admin", "role": "admin"},
            backend=self.backend,
        )
        self.assertEqual(status, 200)
        self.assertFalse(response["updated"])
        self.assertEqual(
            UniversalEventRepository(self.backend).list_events(event_type="CUSTOMER_PROFILE_UPDATED", limit=10), []
        )


if __name__ == "__main__":
    unittest.main()
