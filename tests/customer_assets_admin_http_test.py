#!/usr/bin/env python3
"""Contract/instance admin editing must enforce tenant and lifecycle boundaries."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT / "database", ROOT / "dashboard", ROOT / "core"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from backend import DatabaseConfig
from backend_factory import create_backend
from customer_admin_api import CUSTOMER_ADMIN_CONTRACT, dispatch_customer_admin_post
from customer_assets_admin_http import edit_customer_asset
from customer_management_repository import CustomerManagementRepository
from registry import installation_profile_identity
from registry_repository import RegistryRepository


class CustomerAssetsAdminTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.backend = create_backend(DatabaseConfig(
            driver="sqlite", database=str(Path(self.tmp.name) / "capivara.db"),
        ))
        identity = installation_profile_identity(
            RegistryRepository(self.backend), profile="controller", hostname="asset-admin-controller",
        )
        self.controller_id = str(identity["controller_id"])
        self.manager = CustomerManagementRepository(self.backend)
        customer = self.manager.create_account(
            name="Cliente de testes", legal_name=None, document_type="other",
            document_number="ASSET-EDIT-001", username="edit.customer",
            email="asset.customer@example.test", phone=None,
            controller_id=self.controller_id,
            billing_provider=None, billing_customer_id=None, billing_status=None,
        )
        self.code = customer["customer_code"]
        self.customer_id = int(customer["id"])
        self.admin = {"username": "admin", "role": "admin"}
        self.controller = {"username": "controller", "role": "controller", "scope_id": self.controller_id}
        status, contract = dispatch_customer_admin_post(
            CUSTOMER_ADMIN_CONTRACT,
            {"customer_code": self.code, "game_id": "minecraft", "instance_limit": 2},
            user={"username": "operator", "role": "operator"},
            backend=self.backend,
        )
        self.assertEqual(status, 201)
        self.contract_id = contract["id"]

    def tearDown(self):
        self.backend.close()
        self.tmp.cleanup()

    def act(self, action, changes=None, identifier=None, user=None, customer_code=None):
        return edit_customer_asset(
            {"action": action, "customer_code": customer_code or self.code,
             "id": identifier or self.contract_id, "changes": changes or {}},
            user=user or self.admin, backend=self.backend, root=ROOT,
        )

    def attach(self):
        with self.backend.transaction() as conn:
            conn.execute(
                "INSERT INTO nodes(id,name,role,status) VALUES (?,?,?,?)",
                ("node-for-asset-edit", "Asset edit agent node", "agent", "active"),
            )
            conn.execute(
                "INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?)",
                ("agent-for-asset-edit", self.controller_id, "node-for-asset-edit",
                 "Asset edit agent", "active"),
            )
            conn.execute(
                "INSERT INTO instances(id,node_id,game_id,name,status,controller_id,agent_id,customer_id) "
                "VALUES (?,?,?,?,?,?,?,?)",
                ("instance-for-contract", "node-for-asset-edit", "minecraft",
                 "Before name", "offline", self.controller_id,
                 "agent-for-asset-edit", self.customer_id),
            )
            conn.execute(
                "INSERT INTO instance_contracts(instance_id,contract_id) VALUES (?,?)",
                ("instance-for-contract", self.contract_id),
            )

    def test_empty_contract_product_change_unlocks_modified_distributions(self):
        result = self.act("edit_contract", {"product_variant": "modified", "instance_limit": 3})
        self.assertTrue(result["updated"])
        contract = self.manager.detail(self.code)["contracts"][0]
        self.assertEqual(contract["product_variant"], "modified")
        self.assertEqual(contract["instance_limit"], 3)
        with self.backend.connect() as conn:
            row = conn.execute("SELECT metadata_json FROM service_contracts WHERE id=?", (self.contract_id,)).fetchone()
        import json
        metadata = json.loads(row["metadata_json"])
        self.assertTrue(metadata["entitlements"]["mods"])
        self.assertTrue(metadata["entitlements"]["plugins"])
        from runtime_workspace_catalog import runtime_allowed_by_contract
        self.assertTrue(runtime_allowed_by_contract(
            ROOT, "minecraft", "minecraft.java.paper", metadata
        ))
        self.assertTrue(runtime_allowed_by_contract(
            ROOT, "minecraft", "minecraft.java.fabric", metadata
        ))

    def test_linked_contract_cannot_shrink_below_usage_or_change_product(self):
        self.attach()
        with self.assertRaisesRegex(ValueError, "Limite"):
            self.act("edit_contract", {"instance_limit": 0})
        with self.assertRaisesRegex(ValueError, "migração"):
            self.act("edit_contract", {"product_variant": "modified"})
        with self.assertRaisesRegex(ValueError, "fluxo operacional"):
            self.act("edit_contract", {"status": "cancelled"})
        self.assertEqual(self.manager.detail(self.code)["contracts"][0]["status"], "active")

    def test_rename_only_preserves_ownership_agent_runtime(self):
        self.attach()
        before = self.manager.detail(self.code)["instances"][0]
        edited = self.act("edit_instance", {"name": "Novo nome seguro"}, identifier=before["id"])
        self.assertEqual(edited["name"], "Novo nome seguro")
        after = self.manager.detail(self.code)["instances"][0]
        self.assertEqual(after["name"], "Novo nome seguro")
        for key in ("agent_id", "status", "game_id", "runtime_id", "contract_id"):
            self.assertEqual(before[key], after[key])
        with self.assertRaisesRegex(ValueError, "não editáveis"):
            self.act("edit_instance", {"agent_id": "foreign-agent"}, identifier=before["id"])

    def test_authorization_and_customer_scope(self):
        for user in (
            {"username": "operator", "role": "operator"},
            {"username": "foreign-controller", "role": "controller", "scope_id": "another-controller"},
            {"username": "customer", "role": "customer", "scope_id": self.customer_id},
        ):
            with self.assertRaises(PermissionError):
                self.act("edit_contract", {"instance_limit": 3}, user=user)
        allowed = self.act("edit_contract", {"instance_limit": 3}, user=self.controller)
        self.assertTrue(allowed["updated"])
        with self.assertRaisesRegex(ValueError, "não encontrado"):
            self.act("edit_contract", {"instance_limit": 4}, identifier="contract-foreign")

    def test_delete_only_empty_contract(self):
        self.attach()
        with self.assertRaisesRegex(ValueError, "fluxo"):
            self.act("delete_contract")
        with self.backend.transaction() as conn:
            conn.execute("DELETE FROM instance_contracts WHERE instance_id=?", ("instance-for-contract",))
        deleted = self.act("delete_contract")
        self.assertTrue(deleted["deleted"])
        self.assertEqual(self.manager.detail(self.code)["contracts"], [])


class CustomerAssetsVisualContractsTest(unittest.TestCase):
    def test_eula_only_visible_on_minecraft_java(self):
        css = (ROOT / "dashboard/web/create-server-wizard.css").read_text()
        script = (ROOT / "dashboard/web/runtime-selector.js").read_text()
        self.assertIn("#minecraft-runtime-notice[hidden]{display:none!important}", css)
        self.assertIn('normalize(game) === "minecraft" && normalize(edition) === "java"', script)

    def test_admin_cards_offer_editing_and_controller_animates(self):
        script = (ROOT / "dashboard/web/customer-admin.js").read_text()
        controller_html = (ROOT / "dashboard/web/controller-instance.html").read_text()
        controller_js = (ROOT / "dashboard/web/controller-instance-core.js").read_text()
        self.assertIn('actionButton("Editar",()=>editContract(item))', script)
        self.assertIn('actionButton("Editar",()=>editInstance(item))', script)
        self.assertIn('id="provision-builder"', controller_html)
        self.assertIn('classList.toggle("building",building)', controller_js)


if __name__ == "__main__":
    unittest.main()
