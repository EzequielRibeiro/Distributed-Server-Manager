#!/usr/bin/env python3
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "dashboard" / "web"


class CustomerGameProfileCatalogTest(unittest.TestCase):
    def test_game_catalog_clicks_open_demo_page(self):
        html = (WEB / "customer.html").read_text(encoding="utf-8")
        self.assertIn('#customer-catalog .catalog-game', html)
        self.assertIn('/contract-demo.html?game=', html)
        self.assertNotIn('Você não possui um contrato ativo para', html)

    def test_demo_loads_real_catalog_profiles_with_customer_cookie_session(self):
        html = (WEB / "contract-demo.html").read_text(encoding="utf-8")
        script = (WEB / "contract-demo.js").read_text(encoding="utf-8")
        self.assertIn('id="demo-profiles"', html)
        self.assertIn('/api/catalog/resource-profiles?game=', script)
        self.assertIn('/api/customer/contracts', script)
        self.assertIn('X-Capivara-Auth-Area', script)
        self.assertIn('customer', script)
        self.assertIn('credentials:"same-origin"', script)
        self.assertNotIn('sessionStorage', script)
        self.assertNotIn('Authorization', script)
        self.assertNotIn('/login.html', script)
        self.assertIn('/customer-login.html', script)

    def test_demo_has_no_fake_resource_values(self):
        html = (WEB / "contract-demo.html").read_text(encoding="utf-8")
        self.assertNotIn('8 GB', html)
        self.assertNotIn('25 GB', html)
        self.assertNotIn('Preço exemplo', html)
        self.assertIn('valores reais cadastrados no catálogo', html)


if __name__ == "__main__":
    unittest.main()
