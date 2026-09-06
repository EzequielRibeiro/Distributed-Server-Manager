#!/usr/bin/env python3
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PROFILE_JS = ROOT / "dashboard" / "web" / "customer-profile.js"
CUSTOMER_HTML = ROOT / "dashboard" / "web" / "customer.html"
INSTANCE_HTML = ROOT / "dashboard" / "web" / "customer-instance.html"


class CustomerContractCodeVisibilityTest(unittest.TestCase):
    def test_contract_code_decorator_is_customer_scoped_and_visible(self):
        source = PROFILE_JS.read_text(encoding="utf-8")
        self.assertIn('"X-Capivara-Auth-Area":"customer"', source)
        self.assertIn('/api/customer/contracts', source)
        self.assertIn('/api/runtime/list', source)
        self.assertIn('Contrato: ${code}', source)
        self.assertIn('publicContractCode', source)
        self.assertIn('contract_code', source)
        self.assertIn('contract_id', source)

    def test_contract_code_is_loaded_on_dashboard_and_instance_workspace(self):
        customer = CUSTOMER_HTML.read_text(encoding="utf-8")
        instance = INSTANCE_HTML.read_text(encoding="utf-8")
        self.assertIn('/customer-profile.js?v=3', customer)
        self.assertIn('/customer-profile.js?v=3', instance)
        self.assertIn('id="title"', instance)


if __name__ == "__main__":
    unittest.main()
