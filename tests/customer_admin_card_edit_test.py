#!/usr/bin/env python3
"""Customer consultation card edits: scoped, audited, non-destructive."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "dashboard", ROOT / "database", ROOT / "core"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from backend import DatabaseConfig
from backend_factory import create_backend
from customer_management_repository import CustomerManagementRepository
from customer_admin_api import (
    CUSTOMER_ADMIN_CONTRACT_EDIT,
    CUSTOMER_ADMIN_INSTANCE_EDIT,
    dispatch_customer_admin_post,
)
from registry import installation_profile_identity
from registry_repository import RegistryRepository


class CustomerAdminCardEditTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.backend = create_backend(DatabaseConfig(
            driver="sqlite", database=str(Path(self.tmp.name) / "capivara.db")
        ))
        identity = installation_profile_identity(
            RegistryRepository(self.backend),
            profile="controller", hostname="customer-card-edit-controller",
        )
        self.controller_id = str(identity["controller_id"])
        self.repo = CustomerManagementRepository(self.backend)
        self.customer = self._customer("first")
        self.other = self._customer("other")
        self.contract = self.repo.create_contract(
            customer_code=self.customer["customer_code"],
            game_id="dayz", instance_limit=2, ends_at=None,
            resource_profile_id="low", resource_profile_source="selected",
        )
        self.instance_id = "instance-card-edit-dayz"
        self.node_id = "agent-card-edit-node"
        self.agent_id = "agent-card-edit"
        with self.backend.transaction() as connection:
            connection.execute(
                "INSERT INTO nodes(id,name,role,status) VALUES(?,?,?,?)",
                (self.node_id, "Test Agent", "agent", "active"),
            )
            connection.execute(
                "INSERT INTO agents(id,node_id,controller_id,name,status) VALUES(?,?,?,?,?)",
                (self.agent_id, self.node_id, self.controller_id, "Test Agent", "active"),
            )
            connection.execute(
                "INSERT INTO instances(id,node_id,game_id,name,status,controller_id,agent_id,customer_id) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (self.instance_id, self.node_id, "dayz", "DayZ original", "online",
                 self.controller_id, self.agent_id, self.customer["id"]),
            )
            connection.execute(
                "INSERT INTO instance_contracts(instance_id,contract_id) VALUES(?,?)",
                (self.instance_id, self.contract["id"]),
            )
        self.admin = {"username": "admin", "role": "admin"}
        self.controller = {
            "username": "controller", "role": "controller",
            "scope_id": self.controller_id,
        }

    def tearDown(self):
        self.backend.close()
        self.tmp.cleanup()

    def _customer(self, suffix):
        return self.repo.create_account(
            name="Customer " + suffix, legal_name=None,
            document_type="other", document_number="DOC-" + suffix,
            username="customer." + suffix,
            email=suffix + "@example.test", phone=None,
            controller_id=self.controller_id,
            billing_provider=None, billing_customer_id=None,
            billing_status=None,
        )

    def edit_contract(self, changes, user=None, code=None, contract_id=None):
        return dispatch_customer_admin_post(
            CUSTOMER_ADMIN_CONTRACT_EDIT,
            {
                "customer_code": code or self.customer["customer_code"],
                "contract_id": contract_id or self.contract["id"],
                "changes": changes,
            },
            user=user or self.admin,
            backend=self.backend,
        )

    def edit_instance(self, name, user=None, code=None, **extra):
        return dispatch_customer_admin_post(
            CUSTOMER_ADMIN_INSTANCE_EDIT,
            {"customer_code": code or self.customer["customer_code"],
             "instance_id": self.instance_id, "name": name, **extra},
            user=user or self.admin,
            backend=self.backend,
        )

    def test_contract_edit_updates_limits_and_expiry_without_touching_metadata(self):
        before = self.repo.detail(self.customer["customer_code"])["contracts"][0]
        status, response = self.edit_contract({"instance_limit": 4, "ends_at": "2030-12-31"})
        self.assertEqual(status, 200, response)
        self.assertTrue(response["updated"])
        after = response["detail"]["contracts"][0]
        self.assertEqual(after["instance_limit"], 4)
        self.assertEqual(str(after["ends_at"])[:10], "2030-12-31")
        self.assertEqual(after["resource_profile_id"], before["resource_profile_id"])
        self.assertEqual(after["product_variant"], before["product_variant"])
        self.assertEqual(after["status"], before["status"])
        self.assertEqual(after["instances_used"], 1)
        self.assertEqual(self.edit_contract({"instance_limit": 4})[0], 200)
        self.assertEqual(self.edit_contract({"ends_at": None})[1]["detail"]["contracts"][0]["ends_at"], None)

    def test_contract_limit_below_linked_instances_is_rejected(self):
        for value in (0, -1, 1.2, True, "1.2", 1001):
            with self.subTest(value=value):
                status, response = self.edit_contract({"instance_limit": value})
                self.assertEqual(status, 400, response)
        # A linked instance must prevent lowering the limit below its count.
        other_id = "second-dayz"
        with self.backend.transaction() as connection:
            connection.execute(
                "INSERT INTO instances(id,node_id,game_id,name,status,controller_id,agent_id,customer_id) VALUES(?,?,?,?,?,?,?,?)",
                (other_id, self.node_id, "dayz", "DayZ second", "online",
                 self.controller_id, self.agent_id, self.customer["id"])
            )
            connection.execute(
                "INSERT INTO instance_contracts(instance_id,contract_id) VALUES(?,?)",
                (other_id, self.contract["id"]),
            )
        status, response = self.edit_contract({"instance_limit": 1})
        self.assertEqual(status, 400, response)
        self.assertEqual(self.repo.detail(self.customer["customer_code"])["contracts"][0]["instance_limit"], 2)

    def test_contract_whitelist_and_tenant_scope(self):
        for changes in (
            {"resource_profile_id": "large"},
            {"status": "cancelled"},
            {"game_id": "minecraft"},
            {"ends_at": "bad-date"},
            {"ends_at": "2000-01-01"},
        ):
            with self.subTest(changes=changes):
                self.assertEqual(self.edit_contract(changes)[0], 400)
        self.assertEqual(self.edit_contract({"instance_limit": 3},
            code=self.other["customer_code"])[0], 400)
        self.assertEqual(self.edit_contract({"instance_limit": 3},
            user={"role": "controller", "username": "foreign", "scope_id": "elsewhere"})[0], 403)
        self.assertEqual(self.edit_contract({"instance_limit": 3},
            user={"role": "operator", "username": "operator"})[0], 403)
        self.assertEqual(self.edit_contract({"instance_limit": 3},
            user={"role": "customer", "username": "customer.first"})[0], 403)
        self.assertEqual(self.edit_contract({"instance_limit": 3}, user=self.controller)[0], 200)

    def test_instance_edit_changes_display_name_only(self):
        status, response = self.edit_instance("DayZ Homologação")
        self.assertEqual(status, 200, response)
        self.assertEqual(response["detail"]["instances"][0]["name"], "DayZ Homologação")
        self.assertEqual(response["detail"]["instances"][0]["status"], "online")
        self.assertEqual(response["detail"]["instances"][0]["contract_id"], self.contract["id"])
        self.assertEqual(self.edit_instance("DayZ Homologação")[1]["updated"], False)

    def test_instance_scope_and_unsafe_fields(self):
        for value in ("", " ", "x" * 121, "line\nbreak"):
            self.assertEqual(self.edit_instance(value)[0], 400)
        self.assertEqual(self.edit_instance("Nope", code=self.other["customer_code"])[0], 400)
        self.assertEqual(self.edit_instance("Nope", status="stopped")[0], 400)
        self.assertEqual(self.edit_instance("Nope",
            user={"role": "controller", "username": "foreign", "scope_id": "elsewhere"})[0], 403)
        self.assertEqual(self.edit_instance("Nope",
            user={"role": "operator", "username": "operator"})[0], 403)
        self.assertEqual(self.edit_instance("Controller name", user=self.controller)[0], 200)

    def test_ui_binds_edit_buttons_to_real_api_and_versioned_asset(self):
        script = (ROOT / "dashboard/web/customer-admin.js").read_text()
        html = (ROOT / "dashboard/web/customer-admin.html").read_text()
        self.assertIn('editButton("Editar",form)', script)
        self.assertIn('"/api/admin/customer/contract/update"', script)
        self.assertIn('"/api/admin/customer/instance/update"', script)
        self.assertIn('canEdit=["admin","controller"]', script)
        self.assertIn("/customer-admin.js?v=8", html)
        self.assertIn("/customer-management.css?v=2", html)


if __name__ == "__main__":
    unittest.main()
