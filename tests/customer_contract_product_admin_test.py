#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "dashboard", ROOT / "database", ROOT / "core"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backend import DatabaseConfig
from backend_factory import create_backend
from customer_admin_api import CUSTOMER_ADMIN_CONTRACT, dispatch_customer_admin_post
from customer_management_repository import CustomerManagementRepository
from registry import installation_profile_identity
from registry_repository import RegistryRepository


class CustomerContractProductAdminTest(unittest.TestCase):
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
            hostname="contract-product-controller",
        )
        self.management = CustomerManagementRepository(self.backend)
        self.customer = self.management.create_account(
            name="Minecraft Contract Customer",
            legal_name=None,
            document_type="other",
            document_number="DOC-CONTRACT-PRODUCT",
            username="minecraft.contract",
            email="minecraft.contract@example.test",
            phone=None,
            controller_id=str(identity["controller_id"]),
            billing_provider=None,
            billing_customer_id=None,
            billing_status=None,
        )
        self.operator = {"username": "operator", "role": "operator"}

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def _create_contract(self, **extra):
        payload = {
            "customer_code": self.customer["customer_code"],
            "game_id": "minecraft",
            "instance_limit": 1,
            **extra,
        }
        return dispatch_customer_admin_post(
            CUSTOMER_ADMIN_CONTRACT,
            payload,
            user=self.operator,
            backend=self.backend,
        )

    def test_minecraft_contract_defaults_to_standard_product(self):
        status, contract = self._create_contract()
        self.assertEqual(status, 201)
        self.assertEqual(contract["product_variant"], "standard")
        self.assertEqual(contract["content_mode"], "standard")
        self.assertFalse(contract["entitlements"]["mods"])
        self.assertFalse(contract["entitlements"]["plugins"])
        detail = self.management.detail(self.customer["customer_code"])
        stored = next(item for item in detail["contracts"] if item["id"] == contract["id"])
        self.assertEqual(stored["product_variant"], "standard")
        self.assertEqual(stored["content_mode"], "standard")

    def test_minecraft_modified_product_persists_entitlements(self):
        status, contract = self._create_contract(product_variant="modified")
        self.assertEqual(status, 201)
        self.assertEqual(contract["product_variant"], "modified")
        self.assertEqual(contract["content_mode"], "modified")
        self.assertTrue(contract["entitlements"]["mods"])
        self.assertTrue(contract["entitlements"]["plugins"])
        self.assertTrue(contract["entitlements"]["workshop"])

    def test_invalid_minecraft_product_is_rejected(self):
        status, payload = self._create_contract(product_variant="invented")
        self.assertEqual(status, 400)
        self.assertIn("invalid product_variant", payload["error"])


if __name__ == "__main__":
    unittest.main()
